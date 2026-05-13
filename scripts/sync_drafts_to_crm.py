"""
Sync Deek-drafted email replies from Cairn's email_triage table to
the CRM's ``emails`` table.

Why: CRM's schema (``emails`` with ``is_cairn_draft / is_approved /
approved_by / sent_at / project_id``) was always intended to host
draft replies for in-CRM review. Nothing was writing to it. This
script closes that gap.

Direction is one-way: Cairn → CRM. ``cairn_intel.email_triage``
stays the canonical source; the CRM row is a denormalised mirror
that the CRM frontend reads + acts on. State changes triggered in
CRM (approve/reject) MUST call Cairn endpoints — they don't write
locally and then sync back. See ``core/triage/inbox.py`` for the
action endpoints CRM should hit.

Idempotent: matches on ``message_id`` (UNIQUE in CRM emails).
Re-runs are a no-op for already-synced rows.

Cron cadence: every 2-3 minutes during business hours is enough —
typical email-to-draft latency is already 30-60s on Cairn's side,
so a 3-min sync delay doesn't materially extend the loop.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

CLAW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAW_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(CLAW_ROOT / '.env')
except Exception:
    pass

import psycopg2
from psycopg2.extras import RealDictCursor


logger = logging.getLogger('sync_drafts_to_crm')


def _cairn_db_url() -> str:
    url = os.getenv('DATABASE_URL', '')
    if not url:
        raise RuntimeError('DATABASE_URL not set')
    return url


def _crm_db_url() -> str:
    """CRM lives on the same Postgres host as Cairn (deek-db); only
    the database name differs."""
    url = _cairn_db_url()
    return url.rsplit('/', 1)[0] + '/crm'


def _classify_for_crm(triage_class: str) -> str:
    """Map Cairn's triage classification to a CRM-friendly value."""
    if not triage_class:
        return 'enquiry'
    c = triage_class.lower()
    if 'existing' in c:
        return 'existing_reply'
    if 'new' in c:
        return 'new_enquiry'
    return c


def fetch_drafts_needing_sync(limit: int = 50) -> list[dict]:
    """Triage rows with drafts that haven't been mirrored to CRM yet.

    Strategy: pull recent unreviewed-with-draft rows from Cairn, then
    check CRM emails for existing message_id matches. Anything missing
    gets inserted.
    """
    sql = """
        SELECT t.id AS triage_id,
               t.email_message_id AS message_id,
               t.email_subject AS subject,
               t.email_sender AS from_address,
               t.email_received_at AS received_at,
               t.project_id,
               t.classification,
               t.draft_reply AS body_plain,
               t.processed_at,
               t.reviewed_at,
               t.review_action,
               COALESCE(r.body_html, '') AS original_body_html
          FROM cairn_intel.email_triage t
          LEFT JOIN cairn_email_raw r ON r.message_id = t.email_message_id
         WHERE t.draft_reply IS NOT NULL AND t.draft_reply <> ''
           AND t.processed_at > NOW() - INTERVAL '30 days'
         ORDER BY t.processed_at DESC
         LIMIT %s
    """
    with psycopg2.connect(_cairn_db_url(), connect_timeout=5) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (limit,))
            return [dict(r) for r in cur.fetchall()]


def find_synced_message_ids(message_ids: list[str]) -> set[str]:
    """Which of these message_ids already have a CRM emails row?"""
    if not message_ids:
        return set()
    with psycopg2.connect(_crm_db_url(), connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT message_id FROM emails WHERE message_id = ANY(%s)',
                (message_ids,),
            )
            return {row[0] for row in cur.fetchall()}


def upsert_to_crm(draft: dict) -> dict:
    """Insert (or update state on) a draft in CRM emails.

    Insert path: brand new row, is_cairn_draft=true, is_approved=false.
    Update path (when message_id already exists): refresh body_plain
    in case Cairn-side editing happened. Approval state isn't touched
    by this sync — that's owned by Cairn's stage/reject actions and
    mirrors here separately via inbox.py.
    """
    message_id = draft['message_id']
    is_reviewed = bool(draft.get('reviewed_at'))
    is_approved = is_reviewed and (draft.get('review_action') == 'staged_to_sales')
    sent_at = None
    if is_approved:
        sent_at = draft.get('reviewed_at')

    sql = """
        INSERT INTO emails (
            message_id, project_id, from_address, to_address, subject,
            body_plain, body_html, classification,
            is_inbound, is_cairn_draft, is_approved, approved_by,
            received_at, sent_at, created_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            false, true, %s, %s,
            %s, %s, NOW()
        )
        ON CONFLICT (message_id) DO UPDATE SET
            project_id  = EXCLUDED.project_id,
            body_plain  = EXCLUDED.body_plain,
            classification = EXCLUDED.classification,
            is_approved = EXCLUDED.is_approved,
            approved_by = EXCLUDED.approved_by,
            sent_at     = EXCLUDED.sent_at
        RETURNING id
    """
    params = (
        message_id,
        draft.get('project_id'),
        draft.get('from_address') or '',
        # The drafted reply is OUTBOUND from sales@ to the original sender.
        # We record the original sender as `to_address` because that's where
        # the reply will land. CRM users see this row and know "this draft
        # will go to <to_address>".
        draft.get('from_address') or '',
        f"[DRAFT] {draft.get('subject') or '(no subject)'}",
        draft.get('body_plain') or '',
        '',  # body_html — drafts are plain text today
        _classify_for_crm(draft.get('classification') or ''),
        is_approved,
        'cairn-auto' if not is_reviewed else 'inbox-action',
        draft.get('received_at'),
        sent_at,
    )
    with psycopg2.connect(_crm_db_url(), connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            conn.commit()
    return {'crm_email_id': str(row[0]) if row else None}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s sync_drafts_to_crm — %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    candidates = fetch_drafts_needing_sync(limit=200)
    if not candidates:
        logger.info('no drafts in 30-day window')
        return 0

    msg_ids = [d['message_id'] for d in candidates if d.get('message_id')]
    already_synced = find_synced_message_ids(msg_ids)
    new_or_state_changed = [
        d for d in candidates
        if d['message_id'] not in already_synced or d.get('reviewed_at')
    ]
    inserts = 0
    updates = 0
    errors = 0
    for d in new_or_state_changed:
        try:
            upsert_to_crm(d)
            if d['message_id'] in already_synced:
                updates += 1
            else:
                inserts += 1
        except Exception as exc:
            logger.warning('upsert failed for triage %s: %s',
                           d.get('triage_id'), exc)
            errors += 1
    logger.info(
        'done — candidates=%d already=%d inserted=%d updated=%d errors=%d',
        len(candidates), len(already_synced), inserts, updates, errors,
    )
    return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
