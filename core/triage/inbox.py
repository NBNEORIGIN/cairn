"""
Pending-replies inbox — data layer for /voice/inbox.

The 152 unreviewed triage rows with drafted replies sit in
``cairn_intel.email_triage`` today. This module is the read/write
surface the PWA inbox view + the Manufacture-side "Pending Replies"
panel both consume.

Three primary operations:

  list_pending_drafts()  → cards for the inbox view
  get_pending_draft(id)  → detail panel (full original email +
                           full draft + candidate match audit)
  stage_to_sales(id)     → ship the draft to sales@ for manual
                           review-and-send. Marks the row reviewed.

Plus housekeeping: ``update_draft_text`` for inline edits before
staging, and ``reject_draft`` for "no, don't send anything" cases.

Staging mechanic (v1)
---------------------
Emails a plain-text version of the draft to ``sales@nbnesigns.co.uk``
with subject "[DRAFT] Re: <original subject>". Toby opens it in his
usual mail client, copies the body into a fresh reply addressed to
the original sender, edits, sends from sales@. Crude but works today
with the existing SMTP config and no new IMAP credentials.

Staging mechanic (v2 — upgrade path)
------------------------------------
IMAP APPEND the draft directly to sales@'s Drafts folder so the
draft appears in Toby's mail client already addressed and ready to
send. Blocked on ``IMAP_PASSWORD_SALES`` being set in env. When
that lands, swap the SMTP path for the IMAP one without changing
the PWA contract.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


logger = logging.getLogger(__name__)


SALES_STAGING_ADDR = os.getenv(
    'TRIAGE_STAGING_ADDR', 'sales@nbnesigns.co.uk',
)


def _conn():
    """Cairn-DB connection. Same DATABASE_URL the rest of the
    triage code uses."""
    url = os.getenv('DATABASE_URL', '')
    if not url:
        raise RuntimeError('DATABASE_URL not set')
    return psycopg2.connect(url, connect_timeout=5)


def _crm_conn():
    """CRM-DB connection — same host as Cairn, different database."""
    url = os.getenv('DATABASE_URL', '')
    if not url or '/' not in url:
        raise RuntimeError('DATABASE_URL not set or malformed')
    crm_url = url.rsplit('/', 1)[0] + '/crm'
    return psycopg2.connect(crm_url, connect_timeout=5)


def _mirror_state_to_crm(
    *,
    message_id: Optional[str],
    is_approved: bool,
    approved_by: str,
    review_action: str,
) -> None:
    """Reflect a stage/reject action into CRM's emails table.

    Best-effort — if the CRM-side row doesn't exist yet (sync hasn't
    caught up) or the connection fails, the Cairn-side action still
    succeeded. The next sync_drafts_to_crm run will reconcile.
    """
    if not message_id:
        return
    try:
        with _crm_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE emails
                       SET is_approved = %s,
                           approved_by = %s,
                           sent_at     = CASE WHEN %s THEN NOW() ELSE sent_at END,
                           classification = CASE WHEN %s THEN COALESCE(classification, %s) ELSE classification END
                     WHERE message_id = %s
                       AND is_cairn_draft = true
                    """,
                    (
                        is_approved,
                        approved_by,
                        is_approved,
                        not is_approved,  # only stamp 'rejected' on rejects
                        review_action,
                        message_id,
                    ),
                )
                conn.commit()
    except Exception as exc:
        logger.warning('CRM mirror failed for message_id=%s: %s', message_id, exc)


# ── List / read ────────────────────────────────────────────────────────────

def list_pending_drafts(
    *,
    limit: int = 50,
    offset: int = 0,
    project_id: Optional[str] = None,
    include_reviewed: bool = False,
) -> list[dict]:
    """Cards for the inbox view. Each row carries enough for the
    list display + a small preview of the draft.

    Default ordering: newest first.
    """
    where = ["draft_reply IS NOT NULL AND draft_reply <> ''"]
    params: list = []
    if not include_reviewed:
        where.append('reviewed_at IS NULL')
    if project_id:
        where.append('project_id = %s')
        params.append(project_id)
    where_sql = ' AND '.join(where)

    sql = f"""
        SELECT id, email_subject, email_sender, email_received_at,
               processed_at, classification, project_id,
               LEFT(draft_reply, 240) AS draft_preview,
               LENGTH(draft_reply) AS draft_length,
               reviewed_at, review_action
          FROM cairn_intel.email_triage
         WHERE {where_sql}
         ORDER BY processed_at DESC
         LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rows: list[dict] = []
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            for r in cur.fetchall():
                rows.append(_jsonify(dict(r)))
    return rows


def get_pending_draft(triage_id: int) -> Optional[dict]:
    """Detail view — full email body, full draft, candidate audit."""
    sql = """
        SELECT t.id, t.email_subject, t.email_sender, t.email_received_at,
               t.email_message_id, t.email_mailbox,
               t.processed_at, t.classification, t.classification_confidence,
               t.project_id, t.match_candidates, t.client_name_guess,
               t.draft_reply, t.draft_model,
               t.reviewed_at, t.review_action, t.review_notes,
               COALESCE(r.body_text, r.body_html, '') AS email_body
          FROM cairn_intel.email_triage t
          LEFT JOIN cairn_email_raw r ON r.message_id = t.email_message_id
         WHERE t.id = %s
    """
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (triage_id,))
            row = cur.fetchone()
    if not row:
        return None
    out = _jsonify(dict(row))
    # Enrich with project name from CRM if we have a project_id
    if out.get('project_id'):
        out['project_name'] = _project_name(out['project_id']) or ''
    return out


# ── Write paths ────────────────────────────────────────────────────────────

def update_draft_text(triage_id: int, new_text: str) -> dict:
    """Inline edit of the drafted reply before staging. Doesn't mark
    the row as reviewed — Toby can edit-then-stage-later."""
    if not new_text or not new_text.strip():
        return {'ok': False, 'error': 'empty text'}
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE cairn_intel.email_triage
                      SET draft_reply = %s,
                          draft_model = COALESCE(draft_model, '') || ' | edited@' || NOW()::text
                    WHERE id = %s
                    RETURNING id""",
                (new_text.strip(), triage_id),
            )
            row = cur.fetchone()
            conn.commit()
    if not row:
        return {'ok': False, 'error': 'not found'}
    return {'ok': True, 'triage_id': triage_id, 'length': len(new_text)}


def stage_to_sales(
    triage_id: int,
    *,
    staged_by: str = '',
    dry_run: bool = False,
) -> dict:
    """SMTP-send the draft to sales@ for manual review-and-send.

    Marks the row as reviewed with action='staged_to_sales' on
    success. ``dry_run`` returns what would be sent without actually
    sending — used by the PWA for the preview tab.
    """
    row = get_pending_draft(triage_id)
    if not row:
        return {'ok': False, 'error': 'not found'}
    if not row.get('draft_reply'):
        return {'ok': False, 'error': 'no draft text on this row'}

    subject = f"[DRAFT] {row.get('email_subject') or '(no subject)'}"
    body = _compose_staging_body(row)

    if dry_run:
        return {
            'ok': True,
            'dry_run': True,
            'to': SALES_STAGING_ADDR,
            'subject': subject,
            'body_preview': body[:500],
            'body_length': len(body),
        }

    from scripts.email_triage.digest_sender import smtp_config, send_via_smtp
    cfg = smtp_config()
    if not cfg:
        return {'ok': False, 'error': 'SMTP not configured'}

    try:
        send_via_smtp(cfg, SALES_STAGING_ADDR, subject, body)
    except Exception as exc:
        logger.exception('stage_to_sales SMTP failed for triage %s', triage_id)
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}

    # Mark reviewed
    notes = f'staged_to_sales by {staged_by or "?"}@{datetime.now(timezone.utc).isoformat()}'
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE cairn_intel.email_triage
                      SET reviewed_at = NOW(),
                          review_action = %s,
                          review_notes = COALESCE(NULLIF(review_notes,''), '') || %s
                    WHERE id = %s""",
                ('staged_to_sales', ('\n' if row.get('review_notes') else '') + notes, triage_id),
            )
            conn.commit()
    # Mirror state to CRM emails (best-effort; sync job reconciles if it fails)
    _mirror_state_to_crm(
        message_id=row.get('email_message_id'),
        is_approved=True,
        approved_by=staged_by or 'inbox-action',
        review_action='staged_to_sales',
    )
    return {
        'ok': True,
        'triage_id': triage_id,
        'staged_to': SALES_STAGING_ADDR,
    }


def reject_draft(triage_id: int, *, rejected_by: str = '', reason: str = '') -> dict:
    """Mark the row reviewed without staging anything. Toby's saying
    "this draft is wrong and I don't want it sent in any form" — the
    inbox card goes away, no email is dispatched."""
    notes = f'rejected by {rejected_by or "?"}@{datetime.now(timezone.utc).isoformat()}'
    if reason:
        notes += f' — {reason[:200]}'
    # Need email_message_id for the CRM mirror — look up before the UPDATE
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT email_message_id FROM cairn_intel.email_triage WHERE id = %s',
                (triage_id,),
            )
            mid_row = cur.fetchone()
            message_id = mid_row[0] if mid_row else None
            cur.execute(
                """UPDATE cairn_intel.email_triage
                      SET reviewed_at = NOW(),
                          review_action = %s,
                          review_notes = COALESCE(NULLIF(review_notes,''), '') || %s
                    WHERE id = %s
                    RETURNING id""",
                ('rejected_via_inbox', '\n' + notes, triage_id),
            )
            row = cur.fetchone()
            conn.commit()
    if not row:
        return {'ok': False, 'error': 'not found'}
    _mirror_state_to_crm(
        message_id=message_id,
        is_approved=False,
        approved_by=rejected_by or 'inbox-action',
        review_action='rejected_via_inbox',
    )
    return {'ok': True, 'triage_id': triage_id}


# ── Helpers ────────────────────────────────────────────────────────────────

def _compose_staging_body(row: dict) -> str:
    """The plain-text body emailed to sales@. Designed for the
    "copy this into a fresh reply" workflow: Toby reads the
    metadata, copies the draft text, pastes it into a fresh email
    addressed to the original sender, edits, sends.

    Once IMAP APPEND lands as v2, this function stops being the
    primary staging path — the draft goes straight to sales@'s
    Drafts folder as a properly addressed message instead.
    """
    sender = row.get('email_sender') or '(unknown)'
    subject = row.get('email_subject') or '(no subject)'
    received = row.get('email_received_at') or '?'
    project_name = row.get('project_name') or '(no project mapped)'
    project_id = row.get('project_id') or '?'

    parts = [
        '=' * 60,
        'DEEK DRAFT REPLY — READY FOR REVIEW',
        '=' * 60,
        '',
        f'Original from:    {sender}',
        f'Original subject: {subject}',
        f'Received:         {received}',
        f'Project:          {project_name} ({project_id})',
        '',
        'To send: copy the draft below, click Reply to the original',
        'email from the sender, paste, edit as needed, send.',
        '',
        '=' * 60,
        'DRAFT REPLY',
        '=' * 60,
        '',
        row.get('draft_reply') or '(empty)',
        '',
        '=' * 60,
        f'Mark this draft handled in Cairn:',
        f'  https://deek.nbnesigns.co.uk/voice/inbox/{row.get("id")}',
        '=' * 60,
    ]
    return '\n'.join(parts)


def _jsonify(d: dict) -> dict:
    """Convert datetimes and similar to JSON-friendly forms."""
    for k, v in list(d.items()):
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
    return d


def _project_name(project_id: str) -> Optional[str]:
    """Look up the CRM project name. Same direct-DB pattern as the
    matcher (CRM lives on the same Postgres host)."""
    if not project_id:
        return None
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url or '/' not in db_url:
        return None
    crm_url = db_url.rsplit('/', 1)[0] + '/crm'
    try:
        with psycopg2.connect(crm_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT name FROM "Project" WHERE id = %s',
                    (project_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None
