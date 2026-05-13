"""
Match an incoming email to an existing CRM project.

Two-phase matcher (2026-05-07):

  Phase 1 — Exact sender-email lookup. If the sender's email is stored
  on a CRM project's ``clientEmail`` field, that project wins outright
  and becomes candidate #1 with synthetic score 1.0. This is the
  signal Toby asked for explicitly: "should be straightforward — a
  check between sender email and client email in the CRM". Beats
  the fuzzy search every time when applicable.

  Phase 2 — Hybrid retrieval. Falls back to the CRM's
  ``/api/cairn/search`` endpoint (live pgvector + BM25) with
  email subject + client name guess + sender local-part as the query.
  Used when the exact email lookup misses (new senders, forwarded
  emails, etc.) and to populate alternatives #2 and #3.

The match is deliberately conservative — false positives mean the
triage runner misroutes an email to the wrong project, which confuses
the audit trail. Better to return None than to guess wrong, which is
why the user-facing digest always shows the top 3 with a "PROJECT:
<name>" override affordance.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx


log = logging.getLogger(__name__)


CRM_DEFAULT_BASE_URL = 'https://crm.nbnesigns.co.uk'
CRM_SEARCH_PATH = '/api/cairn/search'
CRM_REQUEST_TIMEOUT = 10.0

# Minimum RRF score from the CRM hybrid search for the digest to
# flag a match as confident. At 2026-04-21 we lowered this from 0.025
# to 0.015 AND changed the digest to always surface the top 3
# candidates so Toby picks — rather than Deek guessing single-
# threshold yes/no. False-positive pressure now lives in the
# reply-back confirmation step.
MIN_MATCH_SCORE = 0.015

# Number of candidate projects the digest shows — best guess plus
# two alternatives.
TOP_CANDIDATES = 3

# Synthetic score returned when an exact sender-email match is found.
# Set well above any RRF score the fuzzy search ever produces so the
# match always sorts to the top and clears MIN_MATCH_SCORE trivially.
EXACT_EMAIL_MATCH_SCORE = 1.0

# Sentinel ``source_type`` for an exact sender-email match. The digest
# email checks this to render a "matched by exact sender-email lookup"
# tag next to the candidate so Toby sees why it ranked #1.
SOURCE_TYPE_EMAIL_EXACT = 'client_email_exact'

# Match an email address out of a sender string. Handles both bare
# ``foo@bar.com`` and the common ``"Display Name" <foo@bar.com>`` form.
_EMAIL_BRACKET_RE = re.compile(r'<([^>]+@[^>]+)>')
_EMAIL_BARE_RE = re.compile(r'([\w.+\-]+@[\w.\-]+\.[\w.\-]+)')


def _bare_email(sender: str) -> str:
    """Return the lowercase bare email from a sender string, or ''."""
    if not sender:
        return ''
    m = _EMAIL_BRACKET_RE.search(sender)
    if m:
        return m.group(1).strip().lower()
    m = _EMAIL_BARE_RE.search(sender)
    if m:
        return m.group(1).strip().lower()
    return sender.strip().lower()


def _crm_db_url() -> str | None:
    """Build a connection string for the CRM database from Deek's own
    DATABASE_URL. Both live on the same Postgres host (`deek-db`); only
    the database name differs. Returns None when DATABASE_URL is unset
    or malformed.

    Used as a bypass when the CRM search API doesn't expose the field
    we need (e.g. clientEmail is on Project but not indexed in CRM's
    search corpus, so /api/cairn/search?q=<email> returns junk).
    """
    url = os.getenv('DATABASE_URL', '')
    if not url or '/' not in url:
        return None
    return url.rsplit('/', 1)[0] + '/crm'


def _exact_email_match_via_crm_db(sender_email: str) -> dict | None:
    """Direct CRM DB lookup — the canonical path for exact-email matching.

    CRM's ``/api/cairn/search`` indexes project content (name, brief,
    embedded original-email body) but NOT the structured ``clientEmail``
    column. So searching for an email returns noise even when there's
    a perfect ``clientEmail`` match in the DB. We bypass the search API
    and query Postgres directly — same connection pattern any
    cross-database read would use.

    Returns the same candidate dict shape as the search-API fallback
    so ``match_project`` can treat both identically. None on any
    failure or no match.
    """
    sender_norm = (sender_email or '').strip().lower()
    if '@' not in sender_norm:
        return None
    crm_url = _crm_db_url()
    if not crm_url:
        return None

    try:
        import psycopg2
        conn = psycopg2.connect(crm_url, connect_timeout=5)
    except Exception as exc:
        log.warning('exact_email_match: CRM DB connect failed: %s', exc)
        return None

    try:
        with conn.cursor() as cur:
            # Prefer the project most recently updated when the same
            # client email appears on multiple projects (often the
            # active one). Falls back to created order if updatedAt
            # isn't populated.
            cur.execute(
                '''
                SELECT id, name, "clientName", "clientEmail",
                       "updatedAt", "createdAt"
                  FROM "Project"
                 WHERE LOWER("clientEmail") = %s
                 ORDER BY "updatedAt" DESC NULLS LAST,
                          "createdAt"  DESC NULLS LAST
                 LIMIT 1
                ''',
                (sender_norm,),
            )
            row = cur.fetchone()
    except Exception as exc:
        log.warning('exact_email_match: CRM DB query failed: %s', exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not row:
        return None

    project_id, name, client_name, client_email, updated_at, _created = row
    return {
        'project_id':       project_id,
        'match_score':      EXACT_EMAIL_MATCH_SCORE,
        'project_name':     name or '',
        'source_type':      SOURCE_TYPE_EMAIL_EXACT,
        'last_activity_at': updated_at.isoformat() if updated_at else '',
        'status':           '',
        'excerpt':          f'Client: {client_name or "?"}',
        'matched_email':    sender_norm,
    }


def _exact_email_match(
    sender_email: str,
    base_url: str,
    token: str,
) -> dict | None:
    """Look up a CRM project whose ``clientEmail`` equals ``sender_email``.

    Resolution order:
      1. Direct CRM DB query (``_exact_email_match_via_crm_db``) — the
         canonical path. CRM's search API doesn't index ``clientEmail``,
         so this is the only reliable way to do exact-email match.
      2. Search API filter (legacy fallback) — kept for the case where
         Deek can't reach the CRM DB but CAN reach the search API (e.g.
         CRM lives on a different host than Cairn in the future).

    Returns a candidate dict on hit, or None.
    """
    sender_norm = (sender_email or '').strip().lower()
    if '@' not in sender_norm:
        return None

    # Primary path — direct DB query
    via_db = _exact_email_match_via_crm_db(sender_norm)
    if via_db is not None:
        return via_db

    # Fallback — search API with metadata-field filter
    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            response = client.get(
                f'{base_url}{CRM_SEARCH_PATH}',
                params={
                    'q': sender_norm,
                    'types': 'project,client',
                    'limit': 20,
                },
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        log.warning('exact_email_match: CRM search fallback failed: %s', exc)
        return None

    if response.status_code != 200:
        return None

    try:
        results = response.json().get('results') or []
    except Exception:
        return None

    for r in results:
        md = r.get('metadata') or {}
        candidate_emails = {
            (md.get('clientEmail') or '').strip().lower(),
            (md.get('client_email') or '').strip().lower(),
            (md.get('email') or '').strip().lower(),
        }
        if sender_norm in candidate_emails:
            return {
                'project_id': r.get('source_id', ''),
                'match_score': EXACT_EMAIL_MATCH_SCORE,
                'project_name': (
                    md.get('project_name')
                    or md.get('title')
                    or r.get('title')
                    or ''
                ),
                'source_type': SOURCE_TYPE_EMAIL_EXACT,
                'last_activity_at': (
                    md.get('last_activity_at') or md.get('updated_at') or ''
                ),
                'status': md.get('status', ''),
                'excerpt': (r.get('excerpt') or '')[:280],
                'matched_email': sender_norm,
            }
    return None


def match_project(
    email: dict,
    classifier_result: dict,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Return a dict with keys {project_id, match_score} or empties.

    ``email`` must have sender, subject, body_text.
    ``classifier_result`` comes from classifier.classify_email().

    If the classifier returned ``classification='existing_project_reply'``
    with a ``client_name_guess`` or ``project_hint``, those are used
    as the CRM search query. Otherwise the subject line is used.
    """
    base = (base_url or os.getenv('CRM_BASE_URL') or CRM_DEFAULT_BASE_URL).rstrip('/')
    token = api_key or (os.getenv('DEEK_API_KEY') or os.getenv('CAIRN_API_KEY') or os.getenv('CLAW_API_KEY', '')).strip()
    if not token:
        return {'project_id': '', 'match_score': 0.0, 'project_name': '', 'candidates': []}

    # ── Phase 1: exact sender-email lookup ──────────────────────────────
    # If the sender is a known CRM client (their email is on the
    # project's ``clientEmail`` field), that's the right project full
    # stop. Bypasses fuzzy search entirely for the common case Toby
    # called out: "should be straightforward — sender email vs CRM
    # client email". 2026-05-07.
    sender_raw = (email.get('sender') or '').strip()
    sender_email = _bare_email(sender_raw)
    exact_match = _exact_email_match(sender_email, base, token) if sender_email else None

    # Build the best query we can from the signals available
    query_parts: list[str] = []
    project_hint = (classifier_result.get('project_hint') or '').strip()
    client_name = (classifier_result.get('client_name_guess') or '').strip()
    subject = (email.get('subject') or '').strip()
    sender = sender_raw

    if project_hint:
        query_parts.append(project_hint)
    if client_name:
        query_parts.append(client_name)
    if subject:
        # Strip "Re:" / "Fw:" prefixes
        cleaned = subject
        for prefix in ('Re:', 'RE:', 'Fw:', 'FW:', 'Fwd:', 'FWD:'):
            cleaned = cleaned.lstrip(prefix).strip()
        query_parts.append(cleaned)
    if sender:
        # Include the sender email local part — often matches
        # clientEmail in Prisma.
        query_parts.append(sender.split('@')[0])

    if not query_parts:
        return {'project_id': '', 'match_score': 0.0, 'project_name': '', 'candidates': []}

    query = ' '.join(query_parts)[:300]

    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            response = client.get(
                f'{base}{CRM_SEARCH_PATH}',
                params={
                    'q': query,
                    'types': 'project,client',
                    'limit': 5,
                },
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        log.warning('project_matcher: CRM search failed: %s', exc)
        return {'project_id': '', 'match_score': 0.0, 'project_name': '', 'candidates': []}

    if response.status_code != 200:
        log.warning(
            'project_matcher: CRM search HTTP %d — %s',
            response.status_code, response.text[:200],
        )
        return {'project_id': '', 'match_score': 0.0, 'project_name': '', 'candidates': []}

    try:
        data = response.json()
    except Exception:
        return {'project_id': '', 'match_score': 0.0, 'project_name': '', 'candidates': []}

    results = data.get('results') or []
    if not results:
        return {'project_id': '', 'match_score': 0.0, 'project_name': '', 'candidates': []}

    # Prefer project rows over client rows — a project ID is what the
    # triage runner actually wants for attaching activity updates.
    project_rows = [r for r in results if r.get('source_type') == 'project']
    target_rows = project_rows or results

    # Build the full candidate list (top N). Phase A wants alternatives
    # in the digest, not just the winner.
    candidates: list[dict] = []
    for r in target_rows[:TOP_CANDIDATES]:
        score = float(r.get('score', 0.0))
        md = r.get('metadata') or {}
        candidates.append({
            'project_id': r.get('source_id', ''),
            'match_score': score,
            'project_name': (
                md.get('project_name')
                or md.get('title')
                or r.get('title')
                or ''
            ),
            'source_type': r.get('source_type', ''),
            'last_activity_at': (
                md.get('last_activity_at') or md.get('updated_at') or ''
            ),
            'status': md.get('status', ''),
            'excerpt': (r.get('excerpt') or '')[:280],
        })

    # ── Merge exact-email match (Phase 1) into the fuzzy results ────────
    # If we found an exact email match, it goes to the top with its
    # synthetic high score. The fuzzy results stay underneath as
    # alternatives in case the same sender has multiple CRM projects
    # — e.g. an enquiry from a recurring client that's actually
    # about a new job, not the one we matched to. The user picks via
    # 1/2/3 or PROJECT: <name> in the digest reply.
    if exact_match:
        already = next(
            (i for i, c in enumerate(candidates)
             if c.get('project_id') == exact_match['project_id']),
            None,
        )
        if already is not None:
            # Already in the fuzzy list — replace with the exact-match
            # version (carries the SOURCE_TYPE_EMAIL_EXACT tag) and
            # move to the top.
            candidates.pop(already)
        candidates.insert(0, exact_match)
        candidates = candidates[:TOP_CANDIDATES]

    if not candidates:
        return {
            'project_id': '', 'match_score': 0.0,
            'project_name': '', 'candidates': [],
        }

    # ── Phase 2 of the learning loop (2026-05-13): feedback-aware ──────
    # boost.  If Toby has reassigned mail from this sender to a
    # specific project in the past year, prefer that project. The
    # function stamps match_score_pre_boost + feedback_boost on each
    # boosted candidate so the digest can show "boosted by your past
    # reassigns" and the audit trail is intact.
    try:
        from core.triage.matcher_feedback import apply_boosts_to_candidates
        candidates, n_boosted = apply_boosts_to_candidates(candidates, sender_raw)
        if n_boosted > 0:
            log.info(
                'project_matcher: applied %d feedback boost(s) for sender=%s',
                n_boosted, sender_raw,
            )
    except Exception as exc:
        # Don't let feedback failures break the matcher — log + carry on
        # with the unboosted candidate list.
        log.warning('project_matcher: feedback boost skipped: %s', exc)

    top = candidates[0]
    # project_id on the return is set only when the top match clears
    # the confidence bar. An exact email match always clears it
    # (synthetic score = 1.0). Callers wanting the unconditional top
    # can read candidates[0]. Backwards compatible with the pre-Phase-A
    # dict shape.
    return {
        'project_id': top['project_id'] if top['match_score'] >= MIN_MATCH_SCORE else '',
        'match_score': top['match_score'],
        'project_name': top['project_name'],
        'candidates': candidates,
    }
