"""
core.triage.sender_associations — Phase 5 of the inbox learning loop.

A learned, dynamic sender ↔ project memory. Every positive action Toby
takes on a draft (archive a matched one, stage to sales@, reassign to
a specific project) writes a vote into ``cairn_intel.sender_project_associations``.
The matcher consults this table before fuzzy CRM search.

Three primitives:

  record_action(sender, project_id, kind)
      Called from inbox.py write paths. ``kind`` is one of:

        'confirmation' — archive / stage on an already-matched draft.
                         Bumps confirmations.
        'override'     — explicit reassign TO this project. Bumps
                         overrides. The caller should also call with
                         kind='rejection' on the *previous* project_id
                         (if any) to record that Toby moved AWAY from
                         it.
        'rejection'    — reassign AWAY (the prior project was wrong).
                         Bumps rejections.

  score_for(sender, project_id)
      Returns a float in [0, 1+] roughly representing P(sender belongs
      to project). Used by the matcher both for auto-match and as a
      boost factor for fuzzy candidates.

  auto_match_for(sender)
      Returns a project_id if a single project dominates the sender's
      history with high confidence — Deek can short-circuit the
      matcher and bind directly. Returns None if the evidence isn't
      strong enough; the matcher then falls through to fuzzy search
      with score_for() boosts applied to each candidate.

Discipline:

  * Never raises. DB failures degrade to ``return None``/``return 0``
    so a transient outage can't break drafting.
  * Sender normalisation matches feedback_rules so case / display-name
    variants don't fragment the count.
  * Writes are synchronous on the inbox-action endpoint so Toby sees
    the matcher get better *during* a review session, not on the next
    cron tick.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

log = logging.getLogger(__name__)

# Scoring constants. Tuned so:
#   - 3 confirmations  → score 0.60  (just below auto-match)
#   - 1 override + 2 confirmations → score 0.70 (just at auto-match)
#   - 2 overrides     → score 0.80  (clear auto-match)
#   - rejections subtract roughly half of what a confirmation adds
WEIGHT_CONFIRMATION = 1.0
WEIGHT_OVERRIDE     = 1.5
WEIGHT_REJECTION    = 1.2  # negative — penalises slightly more than a confirmation rewards

# Auto-match threshold. Above this AND with enough evidence, the
# matcher skips fuzzy search and binds directly. Deliberately
# conservative — false auto-matches frustrate; missed auto-matches
# just mean Toby reviews one more time and the score climbs.
AUTO_MATCH_SCORE_THRESHOLD: float = 0.70
AUTO_MATCH_MIN_ACTIONS: int = 3

# Lookup limit — never need more than this many candidate projects
# for a given sender (Toby's not corresponding with 50 projects per
# sender in real life).
TOP_K: int = 5


ActionKind = Literal['confirmation', 'override', 'rejection']


def _normalise_sender(raw: str) -> str:
    """Pull the bare address out of 'Name <addr@host>' forms, lowercase."""
    if not raw:
        return ''
    s = raw.strip()
    if '<' in s and '>' in s:
        s = s[s.rfind('<') + 1 : s.rfind('>')]
    return s.lower().strip()


# ── Write paths ────────────────────────────────────────────────────────────

def record_action(
    sender: str,
    project_id: str | None,
    kind: ActionKind,
) -> bool:
    """Bump the counter for (sender, project_id) on the given kind.

    Idempotent: re-running with the same data just increments again,
    which is the right behaviour — if Toby reassigns twice, that's
    two pieces of evidence. Returns True on success, False if we
    skipped (empty sender/project_id, DB error).
    """
    sender_n = _normalise_sender(sender)
    if not sender_n or not project_id:
        return False

    column = {
        'confirmation': 'confirmations',
        'override':     'overrides',
        'rejection':    'rejections',
    }.get(kind)
    if column is None:
        log.warning('record_action: unknown kind %r', kind)
        return False

    from core.triage.inbox import _conn
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO cairn_intel.sender_project_associations
                        (sender_email, project_id, {column})
                    VALUES (%s, %s, 1)
                    ON CONFLICT (sender_email, project_id) DO UPDATE
                        SET {column} = cairn_intel.sender_project_associations.{column} + 1
                    """,
                    (sender_n, project_id),
                )
                conn.commit()
        log.info(
            'sender_associations: %s sender=%s project=%s',
            kind, sender_n, project_id,
        )
        return True
    except Exception as exc:
        log.warning(
            'record_action(%s, %s, %s) failed: %s',
            sender_n, project_id, kind, exc,
        )
        return False


# ── Read paths ─────────────────────────────────────────────────────────────

def _score_row(confirmations: int, overrides: int, rejections: int) -> float:
    """Compute the association score for a single (sender, project) row.

    score = (CONF*confs + OVR*overrides - REJ*rejections) / total_actions

    Bounded effectively in [0, ~1.5]. Above ~0.7 the matcher
    auto-matches; below that it's a boost.
    """
    total = confirmations + overrides + rejections
    if total == 0:
        return 0.0
    numerator = (
        WEIGHT_CONFIRMATION * confirmations
        + WEIGHT_OVERRIDE * overrides
        - WEIGHT_REJECTION * rejections
    )
    return max(0.0, numerator / max(total, 1))


def top_associations_for(sender: str, *, limit: int = TOP_K) -> list[dict]:
    """Return up to `limit` (project_id, score, evidence) dicts for
    the sender, ordered by score descending. Empty list if the
    sender has no history or the DB is unavailable.
    """
    sender_n = _normalise_sender(sender)
    if not sender_n:
        return []

    from core.triage.inbox import _conn
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, confirmations, overrides, rejections,
                           last_seen_at
                      FROM cairn_intel.sender_project_associations
                     WHERE sender_email = %s
                    """,
                    (sender_n,),
                )
                rows = cur.fetchall()
    except Exception as exc:
        log.warning('top_associations_for(%s) failed: %s', sender_n, exc)
        return []

    out = []
    for project_id, confs, overs, rejs, last_seen in rows:
        score = _score_row(int(confs), int(overs), int(rejs))
        out.append({
            'project_id':    project_id,
            'score':         score,
            'confirmations': int(confs),
            'overrides':     int(overs),
            'rejections':    int(rejs),
            'total_actions': int(confs) + int(overs) + int(rejs),
            'last_seen_at':  last_seen.isoformat() if last_seen else None,
        })
    out.sort(key=lambda r: r['score'], reverse=True)
    return out[:limit]


def score_for(sender: str, project_id: str) -> float:
    """Score for a single (sender, project_id) pair. Used by the
    matcher to boost fuzzy candidates that have weak-but-non-zero
    history. Returns 0.0 for unknown pairs.
    """
    if not sender or not project_id:
        return 0.0
    for row in top_associations_for(sender, limit=TOP_K):
        if row['project_id'] == project_id:
            return row['score']
    return 0.0


def auto_match_for(sender: str) -> Optional[dict]:
    """Return ``{'project_id', 'score', 'evidence'}`` if the sender has
    strong, unambiguous evidence for a single project. Returns None
    otherwise — the caller should fall through to fuzzy matching.

    Decision rules:
      1. There must be a top candidate with score >= AUTO_MATCH_SCORE_THRESHOLD
         and total_actions >= AUTO_MATCH_MIN_ACTIONS.
      2. The runner-up (if any) must have a meaningfully lower score
         — we don't auto-match when two projects are tied, because a
         tie means the sender corresponds about multiple jobs.
    """
    top = top_associations_for(sender, limit=2)
    if not top:
        return None
    winner = top[0]
    if winner['score'] < AUTO_MATCH_SCORE_THRESHOLD:
        return None
    if winner['total_actions'] < AUTO_MATCH_MIN_ACTIONS:
        return None
    # Tie-break — runner-up must be at least 0.20 lower.
    if len(top) > 1 and (winner['score'] - top[1]['score']) < 0.20:
        return None
    return {
        'project_id': winner['project_id'],
        'score':      winner['score'],
        'evidence':   {
            'confirmations': winner['confirmations'],
            'overrides':     winner['overrides'],
            'rejections':    winner['rejections'],
            'total_actions': winner['total_actions'],
        },
    }
