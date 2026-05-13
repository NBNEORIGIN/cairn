"""
core.triage.matcher_feedback — Phase 2 of the inbox learning loop.

Reads Toby's project-reassignment history off cairn_intel.email_triage
and turns it into per-project score boosts the matcher applies before
picking a winner.

The contract: every Reassign click in /dashboard/inbox writes a
review_notes line shaped:

    'reassigned to <project_id> by <email>@<iso8601> — <reason>'

(see core.triage.inbox.reassign_to_project). We parse the project_id
back out and aggregate per-sender. If Toby has reassigned mail from
sender X to project P three times, project P gets a multiplicative
boost on every future match attempt for sender X.

Boost formula (deliberately conservative):

    boost(corrections) = min(BOOST_CAP, 1.0 + BOOST_STEP * corrections)

with BOOST_STEP=0.15, BOOST_CAP=2.0. One correction → 1.15×; two →
1.30×; ≥7 → 2.00× (cap). That's enough to bump a clear runner-up to
the top spot without drowning out a strong fuzzy signal in the
opposite direction.

Trade-off note: a materialised view would be slightly faster but
adds a schema migration + refresh cron. Per-call SELECT is fine at
our volume (~5-20 triage rows per cron firing).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

BOOST_STEP: float = 0.15
BOOST_CAP: float = 2.0
LOOKBACK_DAYS: int = 365

# Extract the project_id from a review_notes line. Project IDs are
# Prisma cuids (alphanumeric, ~25 chars) — narrow the character class
# so we don't accidentally swallow a trailing 'by' or space.
_REASSIGN_RE = re.compile(r'reassigned to ([a-zA-Z0-9_-]+)')


def _normalise_sender(raw: str) -> str:
    if not raw:
        return ''
    s = raw.strip()
    if '<' in s and '>' in s:
        s = s[s.rfind('<') + 1 : s.rfind('>')]
    return s.lower().strip()


def project_boosts_for(
    sender: str,
    *,
    window_days: int = LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a {project_id: boost_factor} dict for the given sender.

    Empty dict if the sender has no reassignment history (or the DB
    lookup fails — degrade to "no opinion"). Boost values are always
    >= 1.0; the matcher multiplies its existing match_score by the
    boost so anything not in the dict is unaffected.
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
                    SELECT review_notes
                      FROM cairn_intel.email_triage
                     WHERE LOWER(email_sender) LIKE %s
                       AND review_notes LIKE 'reassigned to %%'
                       AND reviewed_at >= NOW() - make_interval(days => %s)
                    """,
                    (f'%{sender_norm}%', window_days),
                )
                notes_rows = cur.fetchall()
    except Exception as exc:
        log.warning('project_boosts_for(%s): %s', sender_norm, exc)
        return {}

    counts: dict[str, int] = {}
    for (notes,) in notes_rows:
        if not notes:
            continue
        # A single triage row can carry multiple reassign lines if the
        # sender bounced between projects — count each one.
        for match in _REASSIGN_RE.finditer(notes):
            pid = match.group(1)
            if pid == '(none)' or not pid:
                continue
            counts[pid] = counts.get(pid, 0) + 1

    return {
        pid: min(BOOST_CAP, 1.0 + BOOST_STEP * n)
        for pid, n in counts.items()
    }


def apply_boosts_to_candidates(
    candidates: list[dict],
    sender: str,
) -> tuple[list[dict], int]:
    """Apply project boosts to a candidate list in-place, then re-sort.

    Phase 5 update (2026-05-13): boost source switched from parsing
    review_notes for 'reassigned to ...' lines to the canonical
    ``cairn_intel.sender_project_associations`` table. Falls back to
    the review_notes parser if the association table read fails (or
    is empty for this sender), so nothing regresses on environments
    where the migration hasn't run yet.

    Each boosted candidate carries an audit trail:
        match_score_pre_boost: float
        feedback_boost:        float
    """
    if not candidates:
        return candidates, 0

    # Primary path — read from the learned association table. Boost
    # factor is derived from the association *score* (which is
    # already normalised to ~[0, 1.5]), squashed into the same
    # [1.0, 2.0] envelope as the legacy boost so the magnitude is
    # comparable.
    boosts: dict[str, float] = {}
    try:
        from core.triage.sender_associations import top_associations_for
        for row in top_associations_for(sender, limit=8):
            if row['score'] <= 0:
                continue
            # score 0   → boost 1.0  (no effect)
            # score 0.5 → boost 1.25
            # score 1.0 → boost 1.50
            # score 1.5 → boost 2.00 (cap)
            boosts[row['project_id']] = min(2.0, 1.0 + 0.5 * row['score'])
    except Exception as exc:
        log.warning('sender_associations lookup failed: %s', exc)

    # Fallback — the legacy review_notes parser. Useful before the
    # association table is backfilled / on a fresh deploy.
    if not boosts:
        boosts = project_boosts_for(sender)

    if not boosts:
        return candidates, 0

    n_boosted = 0
    for cand in candidates:
        pid = cand.get('project_id') or ''
        if pid and pid in boosts:
            pre = float(cand.get('match_score') or 0.0)
            boost = boosts[pid]
            cand['match_score_pre_boost'] = pre
            cand['feedback_boost'] = boost
            cand['match_score'] = pre * boost
            n_boosted += 1
            log.info(
                'matcher_feedback: boosted project=%s sender=%s '
                'pre=%.3f boost=%.2f post=%.3f',
                pid, sender, pre, boost, pre * boost,
            )

    if n_boosted > 0:
        candidates.sort(
            key=lambda c: float(c.get('match_score') or 0.0),
            reverse=True,
        )
    return candidates, n_boosted
