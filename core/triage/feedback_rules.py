"""
core.triage.feedback_rules — the read-back side of the inbox feedback loop.

Phase 1 of the learning-loop plan (see briefs/inbox-learning-loop.md).
Surfaces three hard skip rules that run BEFORE the drafter / matcher,
short-circuiting work for emails Toby has already told Deek to ignore:

  1. Internal domains  — emails from @nbnesigns.com / @nbnesigns.co.uk
                         never need a client-style draft.
  2. Confirmed spam    — a sender Toby marked spam recently is spam.
  3. Confirmed internal — a sender marked internal twice is internal.

The check returns a structured skip reason which the triage_runner
records on the triage row (review_action='auto_skipped', the evidence
goes into review_notes). The row never appears in /dashboard/inbox.

Cheap (one SELECT per email), high-impact: closes the most common
"why is Deek STILL drafting for this person?" complaint immediately.
"""
from __future__ import annotations

from typing import Optional
import logging

log = logging.getLogger(__name__)

# Domains that never warrant a client-style draft. Anything ending in
# one of these is operational chatter between staff.
INTERNAL_DOMAINS: tuple[str, ...] = (
    'nbnesigns.com',
    'nbnesigns.co.uk',
    'phloe.co.uk',
)

# How many strikes before a sender is auto-skipped. Tuned conservatively:
# one spam mark is enough (spam is unambiguous); internal needs two
# (legit clients occasionally use a personal address that happens to
# overlap with a staff name).
SPAM_STRIKES_TO_SKIP: int = 1
INTERNAL_STRIKES_TO_SKIP: int = 2

# How far back to look. Long enough that a sender Toby marked spam
# three months ago still gets skipped; short enough that a former
# client who's come back as a real enquiry isn't permanently muzzled.
LOOKBACK_DAYS: int = 180


def _normalise_sender(raw: str) -> str:
    """Pull the bare email address out of "Name <addr@host>" forms,
    lowercase, strip. Matches the format stored in email_triage."""
    if not raw:
        return ''
    s = raw.strip()
    if '<' in s and '>' in s:
        s = s[s.rfind('<') + 1 : s.rfind('>')]
    return s.lower().strip()


def _domain_of(sender: str) -> str:
    s = _normalise_sender(sender)
    return s.rsplit('@', 1)[-1] if '@' in s else ''


def sender_action_counts(sender: str, *, window_days: int = LOOKBACK_DAYS) -> dict[str, int]:
    """Count this sender's recent review_action history. Returns a dict
    keyed by action (spam / internal_communication / rejected_via_inbox /
    staged_to_sales / archived) with integer counts.

    Empty dict on DB error so callers can degrade to "no opinion".
    """
    from core.triage.inbox import _conn
    sender_norm = _normalise_sender(sender)
    if not sender_norm:
        return {}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT review_action, COUNT(*)
                      FROM cairn_intel.email_triage
                     WHERE LOWER(email_sender) LIKE %s
                       AND review_action IS NOT NULL
                       AND reviewed_at >= NOW() - make_interval(days => %s)
                     GROUP BY 1
                    """,
                    (f'%{sender_norm}%', window_days),
                )
                return {row[0]: int(row[1]) for row in cur.fetchall()}
    except Exception as exc:
        log.warning('sender_action_counts failed for %s: %s', sender_norm, exc)
        return {}


def should_skip_drafting(email_sender: str) -> Optional[dict]:
    """The decision the triage_runner calls before drafting.

    Returns None if drafting should proceed normally. Returns a dict
    ``{'reason': str, 'evidence': dict}`` if the email should be
    short-circuited — the runner writes the triage row with
    review_action='auto_skipped' and skips classification/matching/
    drafting entirely.

    Hard rules in priority order:
      1. Internal domain (cheap string match — no DB hit).
      2. ≥1 prior 'spam' marking from Toby in the lookback window.
      3. ≥2 prior 'internal_communication' markings.

    Tuning lives in the module-level constants above.
    """
    sender = _normalise_sender(email_sender)
    if not sender:
        return None

    # 1) Internal domain — cheapest check, no DB.
    domain = _domain_of(sender)
    if domain in INTERNAL_DOMAINS:
        return {
            'reason': 'internal_domain',
            'evidence': {'domain': domain},
        }

    # 2) + 3) DB lookup for explicit feedback.
    counts = sender_action_counts(sender)
    if not counts:
        return None

    spam_n = counts.get('spam', 0)
    if spam_n >= SPAM_STRIKES_TO_SKIP:
        return {
            'reason': 'sender_marked_spam',
            'evidence': {'spam_count': spam_n, 'window_days': LOOKBACK_DAYS},
        }

    internal_n = counts.get('internal_communication', 0)
    if internal_n >= INTERNAL_STRIKES_TO_SKIP:
        return {
            'reason': 'sender_marked_internal',
            'evidence': {
                'internal_count': internal_n,
                'window_days': LOOKBACK_DAYS,
            },
        }

    return None


def format_skip_note(skip: dict) -> str:
    """Render a skip-reason dict as a one-line review_notes entry."""
    reason = skip.get('reason', 'unknown')
    ev = skip.get('evidence') or {}
    bits = ', '.join(f'{k}={v}' for k, v in ev.items())
    return f'auto-skipped: {reason} ({bits})' if bits else f'auto-skipped: {reason}'
