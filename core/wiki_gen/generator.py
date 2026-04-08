"""
Core wiki generation helpers.

    get_embedding()      — singleton CodeIndexer embed (same pattern as email embedder)
    call_claude()        — Anthropic API call, returns (text, tokens)
    subject_to_title()   — strip email prefixes, normalise
    title_to_filename()  — safe slug filename
    classify_module()    — tag article to Cairn module
    quality_check()      — two-tier gate: local heuristics + optional Claude
    write_wiki_article() — write to disk + chunk + embed into claw_code_chunks
"""
import hashlib
import json
import logging
import os
import re
from pathlib import Path

import anthropic

from core.wiki_gen.db import get_conn, get_db_url

logger = logging.getLogger(__name__)

# Derive paths from __file__ — never hardcode
_CLAW_ROOT = Path(__file__).resolve().parents[2]
_WIKI_DIR = _CLAW_ROOT / 'wiki' / 'modules'

MAX_CHUNK_CHARS = 1500
CLAUDE_MODEL = 'claude-sonnet-4-5'

# ---------------------------------------------------------------------------
# Embedding — singleton CodeIndexer (avoids reconnecting per call)
# ---------------------------------------------------------------------------

_indexer = None


def _get_indexer():
    global _indexer
    if _indexer is None:
        from core.context.indexer import CodeIndexer
        _indexer = CodeIndexer(
            project_id='claw',
            codebase_path=str(_CLAW_ROOT),
            db_url=get_db_url(),
        )
    return _indexer


def get_embedding(text: str) -> list[float]:
    """Embed text using CodeIndexer — same provider chain as the rest of Cairn."""
    return _get_indexer().embed(text)


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

def call_claude(prompt: str, max_tokens: int = 2048) -> tuple[str, int]:
    """
    Call Claude and return (response_text, total_tokens_used).
    Uses ANTHROPIC_API_KEY from environment.
    """
    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    tokens = msg.usage.input_tokens + msg.usage.output_tokens
    return msg.content[0].text, tokens


# ---------------------------------------------------------------------------
# Title / filename helpers
# ---------------------------------------------------------------------------

def subject_to_title(subject: str) -> str:
    """Strip common email prefixes and normalise to a clean article title."""
    cleaned = re.sub(
        r'^(Re:|Fwd:|FW:|How\s+to:|How-to:)\s*',
        '',
        subject,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned or subject


def title_to_filename(title: str) -> str:
    """Convert an article title to a safe wiki filename (slug.md)."""
    slug = re.sub(r'[^a-z0-9\-]', '-', title.lower())
    slug = re.sub(r'-+', '-', slug).strip('-')
    return f'{slug}.md'


# ---------------------------------------------------------------------------
# Module classifier
# ---------------------------------------------------------------------------

_MODULE_KEYWORDS: dict[str, list[str]] = {
    'amazon': ['amazon', 'etsy', 'ebay', 'listing', 'asin',
               'sku', 'marketplace', 'seller central', 'fba'],
    'phloe': ['phloe', 'booking', 'tenant', 'demnurse', 'karate',
              'appointment', 'class timetable'],
    'manufacture': ['manufacture', 'production', 'make', 'print', 'cut',
                    'machine', 'printer', 'mimaki', 'mutoh', 'roland',
                    'rolf', 'laminator', 'plotter'],
    'crm': ['quote', 'invoice', 'client', 'crm', 'project',
            'survey', 'installation', 'customer', 'enquiry'],
    'ledger': ['price', 'pricing', 'cost', 'margin', 'ledger',
               'revenue', 'profit', 'hourly rate', 'labour cost'],
}


def classify_module(title: str, content: str) -> str:
    """Tag article to the appropriate Cairn module. Checks title first, then content."""
    for module, keywords in _MODULE_KEYWORDS.items():
        if any(w in title.lower() for w in keywords):
            return module
    for module, keywords in _MODULE_KEYWORDS.items():
        if any(w in content.lower() for w in keywords):
            return module
    return 'general'


# ---------------------------------------------------------------------------
# Quality gate (two-tier)
# ---------------------------------------------------------------------------

_NBNE_SIGNALS = [
    'nbne', 'alnwick', 'northumberland', 'sign', 'print',
    'vinyl', 'aluminium', 'fascia', 'channel', 'mimaki',
    'mutoh', 'roland', 'amazon', 'etsy',
]

_QUALITY_CHECK_PROMPT = """Review this draft wiki article for NBNE's internal knowledge base.
Return JSON only: {{"pass": true}} or {{"pass": false, "reason": "..."}}.
Reject if:
- Specific financial account numbers or credentials are present
- Claims directly contradict each other without acknowledgement

Article:
{article}
"""


def quality_check(article: str) -> tuple[bool, str, int]:
    """
    Two-tier quality gate. Returns (passed, reason, tokens_used).
    Local heuristics run free. Claude is called only for financial content.
    """
    # Tier 1 — local heuristics
    if len(article.split()) < 200:
        return False, 'too_short', 0

    if not any(s in article.lower() for s in _NBNE_SIGNALS):
        return False, 'no_nbne_signals', 0

    if re.search(r'\b[A-Z]{2}\d{2}[A-Z0-9]{11,}\b', article):
        return False, 'possible_iban', 0

    if re.search(r'(?i)(password|passwd)\s*[:=]\s*\S{6,}', article):
        return False, 'possible_credential', 0

    # Tier 2 — Claude for articles containing financial figures
    if re.search(r'£\d+|\biban\b|\baccount\b', article.lower()):
        try:
            response_text, tokens = call_claude(
                _QUALITY_CHECK_PROMPT.format(article=article[:3000]),
                max_tokens=256,
            )
            result = json.loads(response_text)
            return result.get('pass', False), result.get('reason', 'claude_fail'), tokens
        except json.JSONDecodeError:
            return False, 'claude_parse_error', 0
        except Exception as exc:
            logger.warning('quality_check Claude call failed: %s', exc)
            # Fail safe — don't block on API error; pass locally-clean articles
            return True, 'claude_unavailable', 0

    return True, 'local_pass', 0


# ---------------------------------------------------------------------------
# Article chunking
# ---------------------------------------------------------------------------

def _chunk_article(title: str, content: str) -> list[str]:
    """
    Split a wiki article into embeddable chunks.

    Strategy:
      1. Split on ## section headers — one chunk per section, prefixed with
         the article title for retrieval context.
      2. If a section exceeds MAX_CHUNK_CHARS, slide a word window through it.
      3. If no ## headers exist (short articles), treat as single chunk or
         apply word windowing if over the limit.

    Always prefixes chunks with the article title so retrieval context is
    preserved even when a section is returned in isolation.
    """
    sections = re.split(r'\n(?=## )', content.strip())

    chunks: list[str] = []

    for section in sections:
        if not section.strip():
            continue
        prefixed = f'# {title}\n\n{section}' if not section.startswith('#') else section
        if len(prefixed) <= MAX_CHUNK_CHARS:
            chunks.append(prefixed)
        else:
            # Slide a word window through the section
            words = prefixed.split()
            window = 250  # ~1250 chars at 5 chars/word
            overlap = 25
            step = window - overlap
            for start in range(0, len(words), step):
                chunk = ' '.join(words[start:start + window])
                if chunk.strip():
                    chunks.append(chunk[:MAX_CHUNK_CHARS])

    return chunks or [content[:MAX_CHUNK_CHARS]]


# ---------------------------------------------------------------------------
# Write wiki article to disk + claw_code_chunks
# ---------------------------------------------------------------------------

def write_wiki_article(
    title: str,
    content: str,
    module: str,
    source_email_id: int | None = None,
) -> str:
    """
    Write article markdown to disk and embed all sections into claw_code_chunks.

    Handles UPDATE semantics: deletes any existing chunks for this file_path
    before inserting new ones, so regenerated articles replace stale embeddings.

    Returns the filepath written.
    """
    from pgvector.psycopg2 import register_vector

    filename = title_to_filename(title)
    filepath = _WIKI_DIR / filename
    file_path_key = f'wiki/modules/{filename}'

    # Write markdown to disk
    _WIKI_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding='utf-8')
    logger.info('Wrote wiki article: %s', filepath)

    # Chunk article into embeddable sections
    chunks = _chunk_article(title, content)
    logger.info('Embedding %d chunks for "%s"', len(chunks), title)

    with get_conn() as conn:
        register_vector(conn)

        with conn.cursor() as cur:
            # Delete stale chunks for this article (UPDATE semantics)
            cur.execute(
                "DELETE FROM claw_code_chunks WHERE project_id='claw' AND file_path LIKE %s",
                (f'{file_path_key}%',),
            )

            for i, chunk in enumerate(chunks):
                content_hash = hashlib.sha256(chunk.encode()).hexdigest()
                embedding = get_embedding(chunk)
                chunk_file_path = f'{file_path_key}/{i}' if len(chunks) > 1 else file_path_key

                cur.execute(
                    """
                    INSERT INTO claw_code_chunks
                        (project_id, file_path, chunk_content, chunk_type,
                         chunk_name, content_hash, embedding, subproject_id)
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM claw_code_chunks
                        WHERE content_hash = %s AND project_id = 'claw'
                    )
                    """,
                    (
                        'claw',
                        chunk_file_path,
                        chunk,
                        'wiki',
                        title,
                        content_hash,
                        embedding,
                        module,
                        content_hash,
                    ),
                )

        conn.commit()

    logger.info('Embedded "%s" (%d chunks) into claw_code_chunks', title, len(chunks))
    return str(filepath)


# ---------------------------------------------------------------------------
# Generation log
# ---------------------------------------------------------------------------

def log_generation(
    source_type: str,
    topic: str,
    source_email_ids: list[int],
    article_title: str,
    wiki_filename: str | None,
    quality_passed: bool,
    quality_reason: str,
    chunk_count: int,
    tokens_used: int,
) -> None:
    """Write a row to cairn_wiki_generation_log."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cairn_wiki_generation_log
                    (source_type, topic, source_email_ids, article_title,
                     wiki_filename, quality_passed, quality_reason,
                     chunk_count, tokens_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    source_type,
                    topic,
                    source_email_ids,
                    article_title,
                    wiki_filename,
                    quality_passed,
                    quality_reason,
                    chunk_count,
                    tokens_used,
                ),
            )
            conn.commit()
