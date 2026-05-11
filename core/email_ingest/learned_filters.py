"""
Learned email filters — populated by Toby's replies to triage digests.

Two write paths:

  add_learned_filter(sender, classification, ...)
      Called from core/triage/replies.py::apply_reply when Toby replies
      to a digest with Q0 = SPAM / PERSONAL.

  is_blocked(sender) -> (bool, reason)
      Called from core/email_ingest/filters.py::should_skip_email at
      ingest time. Returns the same (skip, reason) tuple the hardcoded
      filter checks return, so future emails from a learned-spam
      sender skip the digest pipeline entirely.

Default match-type policy (can be overridden by passing match_type):

  SPAM     → domain     (mass-mailing lists often rotate sender
                         local-parts; blocking the whole domain
                         is the right default. Toby can supply
                         'exact' if he wants to block just one
                         address.)
  PERSONAL → exact      (your friend Bob has one email; we don't
                         want to block everything @gmail.com)

The learned filters table is namespaced ``cairn_email_*`` matching
the rest of the email_ingest module. See ``core/email_ingest/db.py``
for the schema.
"""
from __future__ import annotations

import logging
import re
from typing import Optional


log = logging.getLogger(__name__)


_EMAIL_BRACKET_RE = re.compile(r'<([^>]+@[^>]+)>')
_EMAIL_BARE_RE = re.compile(r'([\w.+\-]+@[\w.\-]+\.[\w.\-]+)')


def _bare_email(sender: str) -> str:
    """Extract lowercase bare email from a sender string.
    Mirrors scripts/email_triage/project_matcher._bare_email."""
    if not sender:
        return ''
    m = _EMAIL_BRACKET_RE.search(sender)
    if m:
        return m.group(1).strip().lower()
    m = _EMAIL_BARE_RE.search(sender)
    if m:
        return m.group(1).strip().lower()
    return sender.strip().lower()


def _domain_of(sender_email: str) -> str:
    """Return the lowercase @-suffix (including the @) of an email."""
    if '@' not in sender_email:
        return ''
    return '@' + sender_email.rsplit('@', 1)[1].lower()


def is_blocked(sender_raw: str) -> tuple[bool, str]:
    """Check the learned-filters table for a match against the sender.

    Returns (True, reason) when the sender hits a learned spam or
    personal filter; (False, '') otherwise.

    Reason format mirrors the hardcoded filter strings so log/audit
    grepping is consistent:
        learned_spam:{exact|domain}:{matched_value}
        learned_personal:{exact|domain}:{matched_value}

    Defensive: any DB error is logged and treated as a non-block
    (ingest pipeline continues with the hardcoded filters). We never
    want a learned-filters lookup failure to drop a legit email.
    """
    email = _bare_email(sender_raw)
    if not email or '@' not in email:
        return False, ''
    domain = _domain_of(email)

    from .db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT classification, match_type, sender
                      FROM cairn_email_learned_filters
                     WHERE (match_type = 'exact'  AND LOWER(sender) = %s)
                        OR (match_type = 'domain' AND LOWER(sender) = %s)
                     ORDER BY
                        -- Exact wins over domain (more specific)
                        CASE match_type WHEN 'exact' THEN 0 ELSE 1 END,
                        -- Spam wins over personal (more aggressive skip)
                        CASE classification WHEN 'spam' THEN 0 ELSE 1 END
                     LIMIT 1
                    """,
                    (email, domain),
                )
                row = cur.fetchone()
    except Exception as exc:
        log.warning('learned-filter lookup failed for %s: %s', sender_raw, exc)
        return False, ''

    if not row:
        return False, ''
    classification, match_type, matched = row
    return True, f'learned_{classification}:{match_type}:{matched}'


def add_learned_filter(
    sender_raw: str,
    classification: str,
    *,
    match_type: Optional[str] = None,
    triage_id: Optional[int] = None,
    learned_by: Optional[str] = None,
) -> dict:
    """Insert a learned filter row.

    ``classification`` ∈ {'spam', 'personal', 'newsletter'}.

    ``match_type`` defaults to:
        'domain' for spam
        'exact'  for personal / newsletter

    Returns a dict suitable for logging into the apply_reply summary.
    Idempotent — duplicate sender+match_type+classification is a no-op
    via the unique constraint.
    """
    out: dict = {
        'ok': False,
        'classification': classification,
        'note': '',
    }
    classification = classification.lower().strip()
    if classification not in {'spam', 'personal', 'newsletter'}:
        out['note'] = f'unknown classification {classification!r}'
        return out

    email = _bare_email(sender_raw)
    if not email or '@' not in email:
        out['note'] = f'could not extract email from sender {sender_raw!r}'
        return out

    if match_type is None:
        match_type = 'domain' if classification == 'spam' else 'exact'
    match_type = match_type.lower().strip()
    if match_type not in {'exact', 'domain'}:
        out['note'] = f'unknown match_type {match_type!r}'
        return out

    sender = email if match_type == 'exact' else _domain_of(email)
    if not sender:
        out['note'] = 'empty sender after normalisation'
        return out

    from .db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cairn_email_learned_filters
                        (sender, match_type, classification,
                         learned_from_triage_id, learned_by)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (sender, match_type, classification)
                    DO NOTHING
                    RETURNING id
                    """,
                    (sender, match_type, classification, triage_id, learned_by),
                )
                row = cur.fetchone()
                conn.commit()
    except Exception as exc:
        log.warning('add_learned_filter failed: %s', exc)
        out['note'] = f'{exc.__class__.__name__}: {exc}'
        return out

    out['ok'] = True
    out['sender'] = sender
    out['match_type'] = match_type
    out['filter_id'] = row[0] if row else None
    out['note'] = (
        f'added: {classification} match={match_type} sender={sender}'
        if row else
        f'already present: {classification} match={match_type} sender={sender}'
    )
    return out
