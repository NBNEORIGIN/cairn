"""
Post-run report for a backfill run.

    python -m scripts.backfill.report <backfill_run_id>

Queries ``cairn_intel`` and prints:
    - Run header (status, timing, mode)
    - Counts per source
    - Archetype histogram
    - Signal strength histogram (in 0.1 buckets)
    - Top 10 most novel lessons (by max-pairwise embedding distance)
    - Rows awaiting privacy review (committed=FALSE)
    - Rollback command

Phase 2 ships a minimal version (header + counts + histograms).
Phase 4 onwards fills in the lesson novelty section once lessons
actually exist in the DB.
"""
from __future__ import annotations

import argparse
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m scripts.backfill.report',
        description='Post-run report for a Deek intel backfill run',
    )
    parser.add_argument('run_id', help='backfill_run_id to report on')
    args = parser.parse_args(argv)

    import psycopg2
    dsn = os.getenv('DATABASE_URL', '')
    if not dsn:
        print('DATABASE_URL is not set')
        return 1

    conn = psycopg2.connect(dsn, connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, started_at, ended_at, status, mode,
                          sources_requested, counts_per_source,
                          claude_calls_used, bulk_llm_calls_used, errors
                   FROM cairn_intel.backfill_runs WHERE id = %s""",
                (args.run_id,),
            )
            row = cur.fetchone()
            if not row:
                print(f'No such backfill run: {args.run_id}')
                return 1
            (
                run_id, started_at, ended_at, status, mode,
                sources, counts, claude_used, bulk_used, errors,
            ) = row

            print(f'Backfill run report: {run_id}')
            print('=' * 60)
            print(f'status        : {status}')
            print(f'mode          : {mode}')
            print(f'started_at    : {started_at}')
            print(f'ended_at      : {ended_at}')
            print(f'sources       : {sources}')
            print(f'counts        : {counts}')
            print(f'claude_calls  : {claude_used}')
            print(f'bulk_calls    : {bulk_used}')
            if errors:
                print(f'errors        : {len(errors)}')

            # Archetype histogram for this run.
            cur.execute(
                """SELECT unnest(archetype_tags) AS tag, COUNT(*)
                   FROM cairn_intel.decisions
                   WHERE backfill_run_id = %s
                   GROUP BY tag ORDER BY COUNT(*) DESC""",
                (run_id,),
            )
            tag_rows = cur.fetchall()
            if tag_rows:
                print()
                print('Archetype histogram:')
                for tag, n in tag_rows:
                    print(f'  {tag:<24} {n}')

            # Signal strength histogram in 0.1 buckets.
            cur.execute(
                """SELECT ROUND(signal_strength::numeric, 1) AS bucket, COUNT(*)
                   FROM cairn_intel.decisions
                   WHERE backfill_run_id = %s
                   GROUP BY bucket ORDER BY bucket""",
                (run_id,),
            )
            sig_rows = cur.fetchall()
            if sig_rows:
                print()
                print('Signal strength histogram:')
                for bucket, n in sig_rows:
                    print(f'  {float(bucket):.1f}    {n}')

            # Pending privacy review.
            cur.execute(
                """SELECT COUNT(*) FROM cairn_intel.decisions
                   WHERE backfill_run_id = %s AND committed = FALSE""",
                (run_id,),
            )
            pending = cur.fetchone()[0]
            print()
            print(f'Awaiting privacy review (committed=FALSE): {pending}')

            print()
            print('Rollback (if needed):')
            print('  BEGIN;')
            print(
                f"  UPDATE cairn_intel.backfill_runs "
                f"SET status = 'rolled_back' WHERE id = '{run_id}';"
            )
            print(
                f"  DELETE FROM cairn_intel.decisions "
                f"WHERE backfill_run_id = '{run_id}';"
            )
            print('  COMMIT;')
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
