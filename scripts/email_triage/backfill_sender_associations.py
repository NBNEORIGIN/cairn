"""
One-shot backfill for Phase 5 of the inbox learning loop.

Mines cairn_intel.email_triage history to seed
cairn_intel.sender_project_associations. Run after applying the
migration so the matcher starts with whatever signal Toby has
historically given (rather than waiting for him to action 3+ emails
per sender from scratch).

Source signals (in order of strength):

  1. review_action='staged_to_sales'  → confirmation on the row's
                                        project_id (Toby sent the
                                        Deek-drafted reply)
  2. review_action='archived'         → confirmation (manual send)
  3. 'reassigned to <pid>' in notes   → override on <pid>;
                                        rejection on the row's
                                        previous project_id if
                                        recoverable

Idempotent in spirit (each row contributes exactly once because the
INSERT...ON CONFLICT path is additive — running twice would double-
count). The script truncates the target table first so re-runs are
safe.

Usage (inside the deek-api container):

    docker exec -w /app -e PYTHONPATH=/app deploy-deek-api-1 \\
        python -m scripts.email_triage.backfill_sender_associations \\
        --commit
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys

import psycopg2

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('backfill_sender_associations')


_REASSIGN_RE = re.compile(r'reassigned to ([a-zA-Z0-9_-]+)')


def _normalise_sender(raw: str) -> str:
    if not raw:
        return ''
    s = raw.strip()
    if '<' in s and '>' in s:
        s = s[s.rfind('<') + 1 : s.rfind('>')]
    return s.lower().strip()


def backfill(commit: bool) -> int:
    db = os.getenv('DATABASE_URL')
    if not db:
        raise SystemExit('DATABASE_URL not set')
    conn = psycopg2.connect(db)
    n_rows = 0
    n_confirmations = 0
    n_overrides = 0
    n_rejections = 0

    # Map: (sender, project_id) → {confirmations, overrides, rejections}
    counters: dict[tuple[str, str], dict[str, int]] = {}

    def bump(sender: str, project_id: str, key: str) -> None:
        sender_n = _normalise_sender(sender)
        if not sender_n or not project_id or project_id == '(none)':
            return
        bucket = counters.setdefault((sender_n, project_id), {
            'confirmations': 0, 'overrides': 0, 'rejections': 0,
        })
        bucket[key] += 1

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email_sender, project_id, review_action, review_notes
              FROM cairn_intel.email_triage
             WHERE email_sender IS NOT NULL
            """
        )
        for row in cur.fetchall():
            n_rows += 1
            _, sender, project_id, action, notes = row

            # Confirmation signal — Toby actioned a draft Deek had
            # already matched to a project.
            if project_id and action in ('staged_to_sales', 'archived'):
                bump(sender, project_id, 'confirmations')
                n_confirmations += 1

            # Reassign signal — extract new project + record override.
            # The rejection on the OLD project is harder to recover
            # from history (the original project_id was overwritten
            # when the reassign happened) — accept that we won't get
            # it perfectly; new actions will fill the gap.
            if notes:
                for m in _REASSIGN_RE.finditer(notes):
                    new_pid = m.group(1)
                    if new_pid and new_pid != '(none)':
                        bump(sender, new_pid, 'overrides')
                        n_overrides += 1

    log.info(
        'scanned %d triage rows → %d unique (sender, project) pairs',
        n_rows, len(counters),
    )
    log.info(
        '  confirmations: %d   overrides: %d   rejections: %d',
        n_confirmations, n_overrides, n_rejections,
    )

    if not counters:
        log.info('nothing to write')
        return 0

    if not commit:
        log.info('--dry-run: not writing. Re-run with --commit.')
        return len(counters)

    # Wipe-and-rewrite — backfill is the source of truth on each run,
    # so we don't end up double-counting if the script is re-executed.
    with conn.cursor() as cur:
        cur.execute('TRUNCATE cairn_intel.sender_project_associations')
        for (sender, project_id), c in counters.items():
            cur.execute(
                """
                INSERT INTO cairn_intel.sender_project_associations
                    (sender_email, project_id,
                     confirmations, overrides, rejections)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (sender, project_id,
                 c['confirmations'], c['overrides'], c['rejections']),
            )
        conn.commit()
    log.info('wrote %d association rows', len(counters))
    return len(counters)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--commit', action='store_true',
                   help='actually write to the DB. Without this flag, runs as dry-run.')
    args = p.parse_args(argv)
    backfill(commit=args.commit)
    return 0


if __name__ == '__main__':
    sys.exit(main())
