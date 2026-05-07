"""Wiki-write agent tools.

Closes the gap Toby flagged 2026-04-24: Deek had `search_wiki`
(read) but no `write_wiki` — when Toby asked Deek to "write this
to the wiki", Deek had to either silently fail or persist via
the wrong tool (write_crm_memory).

Two write surfaces exist for long-form Deek-authored knowledge:

1. **Drafts** (`data/wiki-drafts/<slug>.md`) — Deek writes here
   freely via ``write_wiki``. Persisted to the volume-mounted data
   dir so they survive container rebuilds. Indexed into
   ``claw_code_chunks`` with ``chunk_type='wiki'`` so they're
   immediately retrievable via ``search_wiki``. NOT in git.

2. **Canonical wiki** (`wiki/modules/<slug>.md`) — git-tracked,
   committed to origin/master via the GitHub Contents API. Reached
   via ``promote_wiki_to_canon`` AFTER Toby explicitly approves in
   chat ("Do you want me to write this to canon?" → "yes"). Same
   retrieval path; durable across DB restores AND across container
   rebuilds; reviewable in git history.

The two-step approve-then-promote flow (added 2026-05-07) avoids
auto-editing the curated corpus while removing the manual git PR
step Toby was asked to perform previously.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

import httpx

from .registry import RiskLevel, Tool


logger = logging.getLogger(__name__)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = Path(os.getenv('DEEK_DATA_DIR') or (_REPO_ROOT / 'data'))
_DRAFTS_DIR = _DATA_DIR / 'wiki-drafts'

# Canonical wiki dir — bind-mounted from /opt/nbne/deek/wiki on
# Hetzner, so writing here lands on the host filesystem (the git
# checkout) AND is immediately visible inside the container for
# retrieval.
_CANON_DIR = _REPO_ROOT / 'wiki' / 'modules'

# GitHub Contents API target for promoted articles. Toggle via env
# only if the repo ever moves.
_GITHUB_REPO = os.getenv('DEEK_GITHUB_REPO', 'NBNEORIGIN/deek')
_GITHUB_BRANCH = os.getenv('DEEK_GITHUB_BRANCH', 'master')
_GITHUB_API_BASE = 'https://api.github.com'

MAX_CONTENT_CHARS = 60000


def _slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r'[^a-zA-Z0-9]+', '-', text or '').strip('-').lower()
    return (s[:max_len].rstrip('-')) or 'untitled'


def _connect_db():
    import psycopg2
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None
    try:
        return psycopg2.connect(db_url, connect_timeout=5)
    except Exception:
        return None


def _embed_into_chunks(
    *, file_path: str, content: str, chunk_name: str,
) -> tuple[bool, str]:
    """Generate embedding + upsert into claw_code_chunks. Returns
    (ok, detail). Failures are non-fatal — the file write is the
    primary persistence; embedding is the searchability bonus."""
    conn = _connect_db()
    if conn is None:
        return False, 'no DATABASE_URL'
    try:
        from core.wiki.embeddings import get_embed_fn
        embed_fn = get_embed_fn()
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return False, f'embed_fn import: {exc.__class__.__name__}'

    if not embed_fn:
        try:
            conn.close()
        except Exception:
            pass
        return False, 'no embedding model configured'

    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

    try:
        embedding = embed_fn(content[:6000])
    except Exception as exc:
        try:
            conn.close()
        except Exception:
            pass
        return False, f'embed call: {exc.__class__.__name__}'

    try:
        try:
            from pgvector.psycopg2 import register_vector
            register_vector(conn)
        except Exception:
            pass
        with conn.cursor() as cur:
            # Upsert: delete-then-insert keeps existing chunk-write
            # patterns simple
            cur.execute(
                """DELETE FROM claw_code_chunks
                    WHERE project_id = 'deek'
                      AND file_path = %s
                      AND chunk_type = 'wiki'""",
                (file_path,),
            )
            cur.execute(
                """INSERT INTO claw_code_chunks
                    (project_id, file_path, chunk_content, chunk_type,
                     chunk_name, content_hash, embedding, indexed_at,
                     salience, salience_signals, last_accessed_at,
                     access_count)
                   VALUES ('deek', %s, %s, 'wiki', %s, %s, %s::vector,
                           NOW(), 5.0,
                           '{"toby_flag": 0.5, "via": "write_wiki_tool"}'::jsonb,
                           NOW(), 0)""",
                (file_path, content, chunk_name, content_hash, embedding),
            )
            conn.commit()
        return True, 'embedded'
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f'db write: {exc.__class__.__name__}'
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _write_wiki_draft(
    project_root: str,
    title: str,
    content: str,
    tags: list[str] | str | None = None,
    **kwargs,
) -> str:
    """Write a Deek-drafted wiki article to the persistent drafts
    directory + index it into claw_code_chunks for immediate
    search_wiki retrieval.

    Files land at ``data/wiki-drafts/<slug>.md`` (volume-mounted
    on Hetzner) — survives container rebuilds. Toby promotes
    selected drafts to ``wiki/modules/`` via a manual git PR.
    """
    title = (title or '').strip()
    content = (content or '').strip()
    if not title:
        return "write_wiki error: 'title' is required."
    if not content:
        return "write_wiki error: 'content' is required."
    if len(content) > MAX_CONTENT_CHARS:
        return (
            f"write_wiki error: content {len(content)} chars exceeds "
            f"max {MAX_CONTENT_CHARS}; trim or split into multiple "
            'articles.'
        )

    # Normalise tags
    if isinstance(tags, str):
        tag_list = [t.strip() for t in tags.split(',') if t.strip()]
    elif isinstance(tags, list):
        tag_list = [str(t).strip() for t in tags if str(t).strip()]
    else:
        tag_list = []

    slug = _slugify(title)
    target = _DRAFTS_DIR / f'{slug}.md'
    rel_path = f'data/wiki-drafts/{slug}.md'

    # Build the article body. If the user didn't include a top-level
    # heading, prepend one — that matches the convention used by
    # human-authored wiki articles (the embedding code reads `# X`
    # as the chunk_name).
    body_lines: list[str] = []
    if not content.lstrip().startswith('# '):
        body_lines.append(f'# {title}')
        body_lines.append('')
    body_lines.append(content)
    if tag_list:
        body_lines.append('')
        body_lines.append(f'_tags: {", ".join(tag_list)}_')
    body_lines.append('')
    body_lines.append('---')
    body_lines.append(f'_drafted by Deek via write_wiki tool_')
    full_body = '\n'.join(body_lines)

    # File write
    try:
        _DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        # If a file already exists with the same slug, suffix with -2, -3, ...
        if target.exists():
            existing = target.read_text(encoding='utf-8')
            if existing.strip() == full_body.strip():
                return (
                    f'write_wiki: identical draft already exists at '
                    f'{rel_path} — no-op.'
                )
            n = 2
            while True:
                candidate = _DRAFTS_DIR / f'{slug}-{n}.md'
                if not candidate.exists():
                    target = candidate
                    rel_path = f'data/wiki-drafts/{slug}-{n}.md'
                    break
                n += 1
        target.write_text(full_body, encoding='utf-8')
    except Exception as exc:
        return (
            f'write_wiki error: file write failed: '
            f'{exc.__class__.__name__}: {exc}'
        )

    # Embed + index. Failure here means the file exists but isn't
    # search_wiki-discoverable yet — caller can retry or manually
    # run /admin/wiki-sync.
    embed_ok, embed_detail = _embed_into_chunks(
        file_path=rel_path, content=full_body, chunk_name=title,
    )
    embed_summary = (
        'indexed for search_wiki' if embed_ok
        else f'wrote file but indexing failed ({embed_detail}) — '
             'retry via POST /admin/wiki-sync or re-run write_wiki'
    )

    return (
        f'Wrote wiki draft to `{rel_path}`'
        f' (title: "{title}", {len(full_body)} chars'
        + (f', tags: {tag_list}' if tag_list else '')
        + f'). {embed_summary}.\n\n'
        f'DRAFT_SLUG: {slug}\n\n'
        'This is a DRAFT — searchable via search_wiki, but not in the '
        'git-tracked canonical corpus. Ask the user: "Do you want me '
        'to write this to canon?" If they approve, call '
        '`promote_wiki_to_canon` with `draft="' + slug + '"` and the '
        'article will be copied to wiki/modules/, committed to '
        'origin/master, and re-indexed as canonical.'
    )


def _resolve_draft_path(slug_or_filename: str) -> Path | None:
    """Resolve a user-supplied identifier to an actual draft file.

    Accepts: bare slug ("brass-relief-plaque"), filename
    ("brass-relief-plaque.md"), or relative path
    ("data/wiki-drafts/brass-relief-plaque.md"). Returns the
    resolved Path if the file exists under the drafts dir, else
    None. Refuses paths outside the drafts dir (security).
    """
    raw = (slug_or_filename or '').strip()
    if not raw:
        return None
    # Strip any prefix back to the bare filename
    name = Path(raw).name
    if not name.endswith('.md'):
        name = f'{name}.md'
    target = (_DRAFTS_DIR / name).resolve()
    # Confine to drafts dir
    try:
        target.relative_to(_DRAFTS_DIR.resolve())
    except ValueError:
        return None
    if not target.exists():
        return None
    return target


def _commit_to_origin_via_api(
    *, repo_path: str, content: str, message: str,
) -> dict:
    """Commit a single file to origin/master via the GitHub Contents API.

    Avoids the container-vs-host git divergence problem: rather than
    running ``git push`` from inside the container (whose HEAD lags
    the host's git checkout), we PUT directly to GitHub's REST API.
    The host's next ``git pull`` brings the new commit into
    /opt/nbne/deek/, but the file is already canonically in the repo
    and on disk via the bind mount.

    Returns ``{'ok': bool, 'commit_url': str, 'note': str}``. Any
    failure is non-fatal — the file write to wiki/modules/ has
    already happened, so the article is immediately searchable as
    canonical inside Deek even if the commit fails. The note
    explains why; caller surfaces it to the user.
    """
    out = {'ok': False, 'commit_url': '', 'note': ''}
    token = (os.getenv('GITHUB_PAT') or '').strip()
    if not token:
        out['note'] = 'GITHUB_PAT not set — file written locally only'
        return out

    url = f'{_GITHUB_API_BASE}/repos/{_GITHUB_REPO}/contents/{repo_path}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    # Look up current SHA — required if the file already exists
    # (e.g. a previous promotion under the same slug). If it doesn't
    # exist this returns 404 and we create new.
    sha = None
    try:
        r = httpx.get(
            url, headers=headers, params={'ref': _GITHUB_BRANCH}, timeout=15.0,
        )
        if r.status_code == 200:
            sha = (r.json() or {}).get('sha')
    except Exception as exc:
        out['note'] = f'lookup failed: {exc.__class__.__name__}: {exc}'
        return out

    payload = {
        'message': message,
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii'),
        'branch': _GITHUB_BRANCH,
    }
    if sha:
        payload['sha'] = sha

    try:
        r = httpx.put(url, headers=headers, json=payload, timeout=20.0)
    except Exception as exc:
        out['note'] = f'commit failed: {exc.__class__.__name__}: {exc}'
        return out

    if r.status_code in (200, 201):
        try:
            data = r.json() or {}
            out['ok'] = True
            out['commit_url'] = (data.get('commit') or {}).get('html_url', '')
            out['note'] = 'committed to origin/master'
        except Exception:
            out['ok'] = True
            out['note'] = 'committed (response parse failed)'
    else:
        out['note'] = f'GitHub returned HTTP {r.status_code}: {r.text[:200]}'
    return out


def _promote_wiki_to_canon(
    project_root: str,
    draft: str,
    **kwargs,
) -> str:
    """Promote a wiki draft to the canonical, git-tracked corpus.

    REQUIRES Toby's explicit prior approval in chat — Deek must have
    asked "Do you want me to write this to canon?" and received an
    affirmative reply BEFORE calling this tool. The system prompt
    enforces the question; the tool does not re-confirm.

    Steps:
    1. Resolve ``draft`` to a real file under ``data/wiki-drafts/``
    2. Copy the content to ``wiki/modules/<slug>.md`` (host bind
       mount means this lands on the host filesystem too)
    3. Commit to origin/master via the GitHub Contents API so the
       article is durable in git history
    4. Re-embed into ``claw_code_chunks`` under the new file_path so
       retrieval finds it as canonical (drops the draft chunk)
    5. Leave the draft file in place as a redundant safety copy —
       it stays searchable if the canonical write fails partway
       through, and Toby can delete it manually if he wants

    Argument: ``draft`` — the slug, filename, or relative path of
    the draft to promote (e.g. "brass-relief-plaque" or
    "data/wiki-drafts/brass-relief-plaque.md").

    Returns a one-paragraph status string suitable for surfacing to
    Toby in chat.
    """
    target = _resolve_draft_path(draft)
    if target is None:
        return (
            f'promote_wiki_to_canon error: could not resolve draft "{draft}". '
            f'Expected a slug or filename of a file in '
            f'data/wiki-drafts/ — pass the value returned by write_wiki.'
        )

    slug = target.stem
    canon_path = _CANON_DIR / f'{slug}.md'
    canon_rel = f'wiki/modules/{slug}.md'

    try:
        content = target.read_text(encoding='utf-8')
    except Exception as exc:
        return (
            f'promote_wiki_to_canon error: failed to read draft '
            f'{target}: {exc.__class__.__name__}: {exc}'
        )

    # 1. Write to canonical filesystem location (bind-mounted on
    # Hetzner → lands on host git checkout)
    try:
        _CANON_DIR.mkdir(parents=True, exist_ok=True)
        canon_path.write_text(content, encoding='utf-8')
    except Exception as exc:
        return (
            f'promote_wiki_to_canon error: failed to write '
            f'{canon_rel}: {exc.__class__.__name__}: {exc}'
        )

    # 2. Commit to origin/master via GitHub API. Non-fatal if it
    # fails — the file is already on disk and immediately
    # searchable via the bind mount.
    commit = _commit_to_origin_via_api(
        repo_path=canon_rel,
        content=content,
        message=f'docs(wiki): promote "{slug}" to canonical (Toby-approved via Deek)',
    )

    # 3. Re-embed under the canonical path so retrieval finds the
    # canonical version, not the draft. Drop the draft chunk
    # (file_path differs, so the embedding under
    # data/wiki-drafts/<slug>.md is now stale).
    title_match = re.search(r'^#\s+(.+?)$', content, flags=re.MULTILINE)
    chunk_name = (title_match.group(1).strip() if title_match else slug)[:200]
    embed_ok, embed_detail = _embed_into_chunks(
        file_path=canon_rel, content=content, chunk_name=chunk_name,
    )
    # Best-effort: drop the draft's chunk so search doesn't return
    # stale duplicates.
    try:
        conn = _connect_db()
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM claw_code_chunks
                        WHERE project_id = 'deek'
                          AND file_path = %s
                          AND chunk_type = 'wiki'""",
                    (f'data/wiki-drafts/{target.name}',),
                )
                conn.commit()
            conn.close()
    except Exception:
        pass  # non-fatal

    parts = [f'Promoted "{slug}" to canonical: `{canon_rel}`.']
    if commit['ok']:
        if commit['commit_url']:
            parts.append(f'Committed to git: {commit["commit_url"]}')
        else:
            parts.append('Committed to git (origin/master).')
    else:
        parts.append(
            f'Local-file write succeeded; git commit DEFERRED — '
            f'{commit["note"]}. The article is searchable as canonical, '
            f'but won\'t survive a fresh deploy until committed manually.'
        )
    if embed_ok:
        parts.append('Re-indexed under the canonical path.')
    else:
        parts.append(
            f'Re-index failed ({embed_detail}); article will be picked up '
            f'on the next scheduled wiki-freshness sweep.'
        )
    return ' '.join(parts)


promote_wiki_to_canon_tool = Tool(
    name='promote_wiki_to_canon',
    description=(
        'Promote a previously written wiki DRAFT (in data/wiki-drafts/) '
        'to the canonical, git-tracked wiki/modules/ corpus. ONLY call '
        'this AFTER asking the user "Do you want me to write this to '
        'canon?" and receiving an explicit affirmative reply ("yes", '
        '"approve", "go ahead", etc.). Never call without that '
        'confirmation. The tool copies the file, commits to '
        'origin/master via the GitHub API, and re-indexes the article '
        'under the canonical path. Argument: draft — the slug or '
        'filename returned by write_wiki (e.g. "brass-relief-plaque" '
        'or "brass-relief-plaque.md"). Idempotent: re-promoting the '
        'same draft updates the canonical file with the latest content.'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_promote_wiki_to_canon,
    required_permission='write_wiki',
)


write_wiki_tool = Tool(
    name='write_wiki',
    description=(
        'Write a long-form Deek-authored wiki article. Use this '
        'when the user asks you to "remember this", "write this '
        'to the wiki", "document this for next time", or when '
        "you've reasoned through a process / decision / lesson "
        'that future sessions will want to retrieve. The draft '
        'lands at data/wiki-drafts/<slug>.md (persistent volume) '
        'and is immediately indexed into claw_code_chunks for '
        'retrieval via search_wiki. Toby promotes drafts to the '
        'canonical wiki/modules/ corpus via a manual git PR when '
        "they're worth keeping. Arguments: title (required, becomes "
        'the article heading + filename slug), content (required, '
        'the markdown body — can include headings, lists, code '
        'blocks; no top-level # required, will be added if absent), '
        'tags (optional list or comma-separated string). Idempotent '
        'on identical content; suffix-disambiguated on title '
        'collision.'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_write_wiki_draft,
    required_permission='write_wiki',
)


__all__ = [
    'write_wiki_tool',
    '_write_wiki_draft',
    'promote_wiki_to_canon_tool',
    '_promote_wiki_to_canon',
]
