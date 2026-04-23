"""Persistent email-thread ↔ CRM-project associations.

Why: today's triage matcher has a 12% match rate — every inbound
email re-runs heuristic name+subject matching. When Toby confirms a
match (or tags via Telegram), that association should PERSIST so
the next message on the same thread auto-attaches.

This module is the single source of truth for the read + write
side of that persistence, used by:

  * scripts/email_triage/triage_runner.py — at inbound time,
    before calling project_matcher, check if the thread is
    already associated.

  * core/triage/replies.py — at apply_reply time, when Toby
    confirms (match_confirm=affirm or select_candidate), write
    the association.

  * api/routes/telegram.py — /tag and /nottag command handlers.

The table (migration 0014) lives in cairn_intel schema alongside
the other intel / memory infrastructure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Confidence levels, in order of strength
CONFIDENCE_CONFIRMED = 'confirmed'      # Toby said YES in digest reply
CONFIDENCE_MANUAL_TAG = 'manual_tag'    # /tag command
CONFIDENCE_HIGH_AUTO = 'high_auto'      # matcher returned score above threshold
CONFIDENCE_INFERRED = 'inferred'        # weakest — derived from client email etc.

_CONFIDENCE_RANK = {
    CONFIDENCE_CONFIRMED: 4,
    CONFIDENCE_MANUAL_TAG: 3,
    CONFIDENCE_HIGH_AUTO: 2,
    CONFIDENCE_INFERRED: 1,
}

# Sources (for audit — who / what wrote the row)
SOURCE_TRIAGE_REPLY_YES = 'triage_reply_yes'
SOURCE_TELEGRAM_TAG = 'telegram_tag'
SOURCE_AUTO_HIGH_CONFIDENCE = 'auto_high_confidence'
SOURCE_BRIEF_REPLY = 'brief_reply'
SOURCE_ADMIN_MANUAL = 'admin_manual'


@dataclass
class ThreadAssociation:
    id: int
    thread_id: str
    project_id: str
    confidence: str
    source: str
    associated_by: str | None
    client_email: str | None


# ── Write side ──────────────────────────────────────────────────────

def record_association(
    conn,
    *,
    thread_id: str,
    project_id: str,
    source: str,
    confidence: str = CONFIDENCE_CONFIRMED,
    associated_by: str | None = None,
    client_email: str | None = None,
) -> int | None:
    """Upsert an association. Re-recording the same
    (thread_id, project_id) with the SAME-or-LOWER confidence is a
    no-op (keeps the existing stronger record). Higher confidence
    overrides.

    Returns the row id on success; None on failure.
    """
    thread_id = (thread_id or '').strip()
    project_id = (project_id or '').strip()
    if not thread_id or not project_id:
        return None
    if confidence not in _CONFIDENCE_RANK:
        logger.warning('[thread-assoc] unknown confidence %r', confidence)
        confidence = CONFIDENCE_INFERRED
    try:
        with conn.cursor() as cur:
            # Check existing
            cur.execute(
                """SELECT id, confidence FROM cairn_intel.email_thread_associations
                    WHERE thread_id = %s AND project_id = %s""",
                (thread_id, project_id),
            )
            existing = cur.fetchone()
            if existing:
                existing_id, existing_conf = existing
                existing_rank = _CONFIDENCE_RANK.get(existing_conf, 0)
                new_rank = _CONFIDENCE_RANK[confidence]
                if new_rank > existing_rank:
                    cur.execute(
                        """UPDATE cairn_intel.email_thread_associations
                             SET confidence = %s,
                                 source = %s,
                                 associated_by = COALESCE(%s, associated_by),
                                 client_email = COALESCE(%s, client_email),
                                 revoked_at = NULL,
                                 revoked_by = NULL,
                                 revoke_reason = NULL
                           WHERE id = %s""",
                        (confidence, source, associated_by, client_email,
                         int(existing_id)),
                    )
                    conn.commit()
                    return int(existing_id)
                # Lower confidence — just touch last_message_at
                cur.execute(
                    """UPDATE cairn_intel.email_thread_associations
                         SET last_message_at = NOW(),
                             message_count = message_count + 1
                       WHERE id = %s""",
                    (int(existing_id),),
                )
                conn.commit()
                return int(existing_id)

            # Insert new
            cur.execute(
                """INSERT INTO cairn_intel.email_thread_associations
                     (thread_id, project_id, confidence, source,
                      associated_by, client_email, last_message_at)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW())
                   RETURNING id""",
                (thread_id, project_id, confidence, source,
                 associated_by, client_email),
            )
            (new_id,) = cur.fetchone()
            conn.commit()
            return int(new_id)
    except Exception as exc:
        logger.warning('[thread-assoc] record failed: %s', exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def revoke_association(
    conn,
    *,
    thread_id: str | None = None,
    project_id: str | None = None,
    revoked_by: str | None = None,
    reason: str | None = None,
) -> int:
    """Revoke by thread_id (all associations for that thread) OR by
    (thread_id + project_id). Returns the count of rows revoked."""
    if not thread_id:
        return 0
    try:
        with conn.cursor() as cur:
            if project_id:
                cur.execute(
                    """UPDATE cairn_intel.email_thread_associations
                         SET revoked_at = NOW(),
                             revoked_by = %s,
                             revoke_reason = %s
                       WHERE thread_id = %s
                         AND project_id = %s
                         AND revoked_at IS NULL""",
                    (revoked_by, reason, thread_id, project_id),
                )
            else:
                cur.execute(
                    """UPDATE cairn_intel.email_thread_associations
                         SET revoked_at = NOW(),
                             revoked_by = %s,
                             revoke_reason = %s
                       WHERE thread_id = %s
                         AND revoked_at IS NULL""",
                    (revoked_by, reason, thread_id),
                )
            count = cur.rowcount
            conn.commit()
        return int(count or 0)
    except Exception as exc:
        logger.warning('[thread-assoc] revoke failed: %s', exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


# ── Read side ───────────────────────────────────────────────────────

def lookup_project_for_thread(
    conn, thread_id: str,
) -> ThreadAssociation | None:
    """Find the active association for this thread, strongest
    confidence wins. None if no association exists (or all revoked)."""
    thread_id = (thread_id or '').strip()
    if not thread_id:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, thread_id, project_id, confidence, source,
                          associated_by, client_email
                     FROM cairn_intel.email_thread_associations
                    WHERE thread_id = %s
                      AND revoked_at IS NULL
                    ORDER BY
                      CASE confidence
                        WHEN 'confirmed'    THEN 4
                        WHEN 'manual_tag'   THEN 3
                        WHEN 'high_auto'    THEN 2
                        WHEN 'inferred'     THEN 1
                        ELSE 0 END DESC,
                      first_matched_at DESC
                    LIMIT 1""",
                (thread_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning('[thread-assoc] lookup failed: %s', exc)
        return None
    if not row:
        return None
    return ThreadAssociation(
        id=int(row[0]),
        thread_id=row[1],
        project_id=row[2],
        confidence=row[3],
        source=row[4],
        associated_by=row[5],
        client_email=row[6],
    )


def recent_associations_for_user(
    conn, user_email: str | None = None, limit: int = 5,
) -> list[ThreadAssociation]:
    """Return the N most recently matched associations (optionally
    filtered by who associated them). Used by Telegram /tag to
    infer which thread the user means when they tag without a
    thread_id."""
    try:
        with conn.cursor() as cur:
            if user_email:
                cur.execute(
                    """SELECT id, thread_id, project_id, confidence, source,
                              associated_by, client_email
                         FROM cairn_intel.email_thread_associations
                        WHERE revoked_at IS NULL
                          AND associated_by = %s
                        ORDER BY first_matched_at DESC
                        LIMIT %s""",
                    (user_email, int(limit)),
                )
            else:
                cur.execute(
                    """SELECT id, thread_id, project_id, confidence, source,
                              associated_by, client_email
                         FROM cairn_intel.email_thread_associations
                        WHERE revoked_at IS NULL
                        ORDER BY first_matched_at DESC
                        LIMIT %s""",
                    (int(limit),),
                )
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning('[thread-assoc] recent lookup failed: %s', exc)
        return []
    return [
        ThreadAssociation(
            id=int(r[0]), thread_id=r[1], project_id=r[2],
            confidence=r[3], source=r[4],
            associated_by=r[5], client_email=r[6],
        )
        for r in rows
    ]


def last_open_digest_thread_for_user(
    conn, user_email: str,
) -> dict | None:
    """Telegram /tag lookup helper: find the most recent triage
    digest that was sent to this user and (a) hasn't already been
    confirmed via reply-back, (b) has a known thread_id we can
    bind to. Returns {triage_id, thread_id, subject} or None.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT t.id, t.email_subject,
                          coalesce(r.thread_id, r.message_id) AS thread_id
                     FROM cairn_intel.email_triage t
                     LEFT JOIN cairn_email_raw r
                       ON r.message_id = t.email_message_id
                    WHERE t.reviewed_at IS NULL
                      AND t.sent_to_toby_at IS NOT NULL
                      AND t.classification = 'existing_project_reply'
                    ORDER BY t.sent_to_toby_at DESC
                    LIMIT 1""",
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning('[thread-assoc] last open digest failed: %s', exc)
        return None
    if not row or not row[2]:
        return None
    return {
        'triage_id': int(row[0]),
        'subject': row[1] or '',
        'thread_id': row[2],
    }


# ── Thread-id lookup from triage row ────────────────────────────────

def thread_id_for_triage(conn, triage_id: int) -> str | None:
    """Resolve a triage row's source email → thread_id. Used by the
    reply processor when Toby confirms a match — we know the
    triage_id and need to write the association against the
    CLIENT's thread (not the digest's thread, which is a separate
    conversation between Toby and Deek)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT coalesce(r.thread_id, r.message_id)
                     FROM cairn_intel.email_triage t
                     JOIN cairn_email_raw r
                       ON r.message_id = t.email_message_id
                    WHERE t.id = %s""",
                (int(triage_id),),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning('[thread-assoc] thread_id_for_triage failed: %s', exc)
        return None
    return (row[0] if row else None) or None


__all__ = [
    'ThreadAssociation',
    'CONFIDENCE_CONFIRMED',
    'CONFIDENCE_MANUAL_TAG',
    'CONFIDENCE_HIGH_AUTO',
    'CONFIDENCE_INFERRED',
    'SOURCE_TRIAGE_REPLY_YES',
    'SOURCE_TELEGRAM_TAG',
    'SOURCE_AUTO_HIGH_CONFIDENCE',
    'SOURCE_BRIEF_REPLY',
    'SOURCE_ADMIN_MANUAL',
    'record_association',
    'revoke_association',
    'lookup_project_for_thread',
    'recent_associations_for_user',
    'last_open_digest_thread_for_user',
    'thread_id_for_triage',
]
