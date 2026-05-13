"""
core.triage.drafter_feedback — Phase 3 of the inbox learning loop.

Reads Toby's draft-rejection history off cairn_intel.email_triage and
turns it into "AVOID" examples injected into the drafter's prompt.

The contract: every Reject click in /dashboard/inbox writes a
review_notes line shaped:

    'rejected by <email>@<iso8601> — <reason>'

(see core.triage.inbox.reject_draft). We parse the reason out and
feed the most recent N back to the drafter as explicit negative
examples. This is *content-level* feedback: it doesn't change which
project gets matched (Phase 2 does that) and doesn't change whether
a draft is generated at all (Phase 1 does that) — it changes the
text Deek produces.

Trade-off note: sender-level scope is the safest starting point.
Broader scopes (same classification, semantic similarity over
rejection embeddings) are higher-recall but also higher false-positive
risk — a rejection on enquiry A inadvertently muzzling drafts on
enquiry B. Start narrow; broaden once we have a few weeks of data
on how often the AVOID block actually matches a real pattern.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

# How many recent rejections to inject. Five is plenty — beyond that
# the LLM starts ignoring late items in the list. The drafter's
# prompt is already ~1500 tokens; we can spare ~5 × 30 = 150 more.
MAX_NEGATIVE_EXAMPLES: int = 5

# Default lookback. Long enough to catch a rejection from a month ago
# but short enough that an old "I was in a bad mood" rejection on a
# template Toby actually likes now doesn't permanently muzzle it.
LOOKBACK_DAYS: int = 90

# The reason follows ' — ' (em-dash) in the canonical review_notes
# format. Tolerate variants that may creep in over time.
_REASON_RE = re.compile(
    r'rejected by [^@]+@[^ ]+ ?[—\-]+ (.+?)(?:\n|$)',
    re.IGNORECASE,
)


def _normalise_sender(raw: str) -> str:
    if not raw:
        return ''
    s = raw.strip()
    if '<' in s and '>' in s:
        s = s[s.rfind('<') + 1 : s.rfind('>')]
    return s.lower().strip()


def _extract_reasons(notes_blob: str) -> list[str]:
    """A single review_notes column can carry multiple rejection lines
    appended over time. Extract the reason text from each."""
    out: list[str] = []
    for m in _REASON_RE.finditer(notes_blob or ''):
        reason = m.group(1).strip()
        if reason:
            out.append(reason[:280])  # truncate runaway pastes
    return out


def recent_rejections_for(
    sender: str,
    *,
    limit: int = MAX_NEGATIVE_EXAMPLES,
    window_days: int = LOOKBACK_DAYS,
) -> list[str]:
    """Return up to ``limit`` rejection reasons from this sender's
    history, newest-first. Empty list on no history or DB error.
    """
    sender_norm = _normalise_sender(sender)
    if not sender_norm:
        return []
    from core.triage.inbox import _conn
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT review_notes
                      FROM cairn_intel.email_triage
                     WHERE LOWER(email_sender) LIKE %s
                       AND review_action = 'rejected_via_inbox'
                       AND review_notes IS NOT NULL
                       AND reviewed_at >= NOW() - make_interval(days => %s)
                     ORDER BY reviewed_at DESC
                     LIMIT %s
                    """,
                    (f'%{sender_norm}%', window_days, limit * 3),
                    # ×3 because some rows might have empty/unparseable reasons
                )
                rows = cur.fetchall()
    except Exception as exc:
        log.warning('recent_rejections_for(%s): %s', sender_norm, exc)
        return []

    reasons: list[str] = []
    for (notes,) in rows:
        for r in _extract_reasons(notes):
            if r not in reasons:  # de-dupe identical reasons
                reasons.append(r)
            if len(reasons) >= limit:
                return reasons
    return reasons


def format_avoid_block(reasons: list[str]) -> str:
    """Render the reasons as a prompt-ready ## AVOID block.

    Phrased as feedback from Toby (not Deek's own self-correction)
    because LLMs respond better to "the human told you not to do X"
    than to "you used to do X". Empty input → empty string.
    """
    if not reasons:
        return ''
    lines = ['## AVOID — Toby has rejected drafts for this sender '
             'with these reasons. Do NOT repeat these patterns:']
    for r in reasons:
        # Keep each one concise — the LLM doesn't need timestamps or
        # the rejected-by field, just the substance.
        lines.append(f'  - {r}')
    return '\n'.join(lines)
