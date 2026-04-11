"""
Source 7 — principles.

Extracts standalone business principles / heuristics / rules from
two sources:

- **Phase A** — wiki articles on disk (``D:/claw/wiki/**/*.md``).
  The LAN ``claw_code_chunks`` table is the federation layer that
  indexes wiki content into pgvector, but we read the raw files here
  because (a) we don't need the embedding, only the text, and (b)
  an orphan transaction on the LAN DB has been observed blocking
  claw_code_chunks reads during active cairn-api startup — reading
  disk removes that dependency entirely.

- **Phase B** — outgoing messages from the ``toby@`` mailbox, Haiku
  extracted. Deferred to a follow-up session — it needs a filtered
  query against ``cairn_email_raw`` that the Phase 7 emails source
  will own.

For Phase 4 this source ships with wiki extraction only. When Phase
B lands the ``iter_records`` loop grows a second branch and the
deduplication runs across both phases together.

What we do per wiki file
------------------------

1. Read the markdown body.
2. Call Haiku with the extraction prompt from the brief:
   *"Extract any sentence in which the author states a general rule,
   principle, heuristic, or lesson about how to handle business
   situations. Return verbatim sentences only, one per line. Ignore
   one-off observations, project-specific numbers, and
   process-description sentences."*
3. Split the response into candidate sentences.
4. Embed each sentence (via the provided ``embed_fn``) and drop any
   whose cosine similarity to a previously-kept principle is ≥ 0.92.
5. Emit one ``RawHistoricalRecord`` per surviving principle, shaped
   as: ``source_type='principle'``, ``signal_strength=1.0``,
   ``chosen_path=<sentence>``, ``rejected_paths=None``,
   and an outcome row whose ``verbatim_lesson`` is the sentence
   itself (so retrieval lands on the principle exactly as written).

Budget is respected: each wiki file costs ONE Haiku call
(extraction). No Sonnet / Opus calls — the sentence IS the lesson,
no LLM rewrite.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .base import HistoricalSource, RawHistoricalRecord, RawOutcome


log = logging.getLogger(__name__)

EmbedFn = Callable[[str], list[float] | None]


PRINCIPLE_EXTRACTION_SYSTEM = (
    'You are a careful reader extracting reusable business wisdom from '
    'process documentation. Your job: return any sentence in which the '
    'author states a general rule, principle, heuristic, or lesson about '
    'how to handle business situations. '
    '\n\n'
    'Rules:\n'
    '- Return verbatim sentences only. Do not paraphrase. Do not add '
    'commentary. Do not number or bullet.\n'
    '- One sentence per line. No blank lines.\n'
    '- Ignore one-off observations, project-specific numbers, '
    'file-path references, dates, and process-step descriptions.\n'
    '- If a paragraph contains a general rule wrapped in specific '
    'context, return only the rule sentence.\n'
    '- If the document contains no general rules, return the single '
    'line: NONE\n'
    '- Do not invent wisdom that is not in the text.'
)


class PrinciplesSource:
    """Wiki-on-disk principle extraction."""

    name: str = 'principles'
    source_type: str = 'principle'

    def __init__(
        self,
        wiki_dir: Path,
        tagger: Any,  # scripts.backfill.archetype_tagger.ArchetypeTagger
        embed_fn: EmbedFn,
        min_length: int = 25,
        dedupe_threshold: float = 0.92,
        max_files: int | None = None,
    ):
        self.wiki_dir = Path(wiki_dir)
        self.tagger = tagger
        self.embed_fn = embed_fn
        self.min_length = min_length
        self.dedupe_threshold = dedupe_threshold
        self.max_files = max_files

    # ── Public iteration ────────────────────────────────────────────────

    def iter_records(self) -> Iterator[RawHistoricalRecord]:
        if not self.wiki_dir.exists():
            log.warning('principles: wiki_dir does not exist: %s', self.wiki_dir)
            return

        kept: list[tuple[list[float], str]] = []  # (embedding, sentence)
        now = datetime.now(tz=timezone.utc)

        files = sorted(self.wiki_dir.rglob('*.md'))
        if self.max_files is not None:
            files = files[: self.max_files]

        for file in files:
            try:
                body = file.read_text(encoding='utf-8', errors='replace')
            except Exception as exc:
                log.warning('principles: could not read %s: %s', file, exc)
                continue
            body = body.strip()
            if not body or len(body) < 80:
                continue

            try:
                extracted = self._extract(body, file.name)
            except Exception as exc:
                log.warning('principles: extraction failed on %s: %s', file, exc)
                continue

            for sentence in extracted:
                sentence = sentence.strip()
                if len(sentence) < self.min_length:
                    continue
                if _looks_process_y(sentence):
                    continue

                embedding = self._embed(sentence)
                if embedding is None:
                    continue

                if _is_duplicate(embedding, kept, self.dedupe_threshold):
                    continue

                kept.append((embedding, sentence))
                yield self._build_record(
                    sentence=sentence,
                    source_file=file,
                    decided_at=now,
                )

    # ── Helpers ─────────────────────────────────────────────────────────

    def _extract(self, body: str, source_label: str) -> list[str]:
        """Call Haiku to pull principle sentences from the body."""
        # We reach straight into the tagger's client to avoid polluting
        # the ArchetypeTagger public API with extraction methods.
        # Budget is still consumed via tagger.budget.
        self.tagger.budget.consume_bulk(source='principles')
        client = self.tagger._get_client()  # same anthropic.Anthropic instance
        resp = client.messages.create(
            model=self.tagger.model,
            max_tokens=700,
            system=PRINCIPLE_EXTRACTION_SYSTEM,
            messages=[{
                'role': 'user',
                'content': body[:12000],  # generous but bounded
            }],
        )
        raw = _first_text(resp).strip()
        if not raw or raw.strip().upper() == 'NONE':
            return []
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _embed(self, text: str) -> list[float] | None:
        try:
            vec = self.embed_fn(text[:2000])
        except Exception:
            return None
        if not vec:
            return None
        return list(vec)

    def _build_record(
        self,
        sentence: str,
        source_file: Path,
        decided_at: datetime,
    ) -> RawHistoricalRecord:
        short_hash = hashlib.sha256(sentence.encode('utf-8')).hexdigest()[:12]
        deterministic_id = f'backfill_principle_{short_hash}'

        return RawHistoricalRecord(
            deterministic_id=deterministic_id,
            source_type='principle',
            decided_at=decided_at,
            chosen_path=sentence,
            context_summary=sentence,
            # Tags still come from Haiku — the principle sentence goes
            # through the normal tagger.tag path so the taxonomy stays
            # source-agnostic.
            archetype_tags=None,
            rejected_paths=None,
            signal_strength=1.0,
            case_id=None,
            raw_source_ref={
                'source_file': str(source_file.relative_to(source_file.anchor)),
                'file_name': source_file.name,
            },
            needs_privacy_scrub=False,
            needs_privacy_review=False,
            outcome=RawOutcome(
                observed_at=decided_at,
                actual_result='Principle derived from wiki article.',
            ),
            verbatim_lesson=sentence,
            verbatim_lesson_model='toby_verbatim',
        )


# ── Helpers (module-level so tests can import them) ────────────────────


def _looks_process_y(sentence: str) -> bool:
    """Filter out sentences that look like process instructions rather than wisdom.

    Heuristic — errs on the side of keeping things. The real filter
    is the Haiku extraction prompt; this is a defence in depth.
    """
    lowered = sentence.lower()
    if lowered.startswith(('run ', 'click ', 'navigate to ', 'open ', 'go to ')):
        return True
    if any(token in lowered for token in (' http://', ' https://', '.py', '.md ')):
        return True
    if re.search(r'\bstep \d+\b', lowered):
        return True
    return False


def _cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _is_duplicate(
    embedding: list[float],
    kept: list[tuple[list[float], str]],
    threshold: float,
) -> bool:
    for existing, _ in kept:
        if _cosine(embedding, existing) >= threshold:
            return True
    return False


def _first_text(response: Any) -> str:
    try:
        for block in response.content:
            if getattr(block, 'type', '') == 'text':
                return block.text
    except Exception:
        pass
    return ''
