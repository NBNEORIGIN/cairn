#!/usr/bin/env python3
"""Backfill the crosslink graph from existing memory rows (Brief 3 Phase A).

One-off run against claw_code_chunks where chunk_type='memory'. For
each row: extract entities, upsert nodes, link memory↔entity, reinforce
co-occurrence edges. Idempotent — all writes use ON CONFLICT DO UPDATE
semantics, so re-running against the same rows does not double-count.

Usage:
    python scripts/seed_entity_graph.py           # all memory rows
    python scripts/seed_entity_graph.py --limit 5 # first 5 (testing)
    python scripts/seed_entity_graph.py --dry-run # report only

Exit codes:
    0 — ran to completion
    1 — fatal setup error (DB down, migration not applied, etc.)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--limit', type=int, default=0,
                    help='Stop after processing N rows (0 = all)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Extract + report; do not write to graph tables')
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    log = logging.getLogger('seed')

    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        log.error('DATABASE_URL not set')
        return 1
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=5)
    except Exception as exc:
        log.error('db connect failed: %s', exc)
        return 1

    from core.memory.entities import (
        extract_entities, outcome_signal, upsert_entities_and_edges,
    )

    t0 = time.monotonic()
    processed = 0
    total_nodes = 0
    total_edges = 0
    zero_entity_rows = 0

    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, chunk_content
                     FROM claw_code_chunks
                    WHERE chunk_type = 'memory'
                    ORDER BY id ASC"""
            )
            rows = cur.fetchall()
        log.info('memory rows to scan: %d', len(rows))
        if args.limit > 0:
            rows = rows[:args.limit]

        for chunk_id, content in rows:
            content = content or ''
            refs = extract_entities(content)
            if not refs:
                zero_entity_rows += 1
                processed += 1
                continue

            # Deek write-back memories include "Outcome: <x>" as a line;
            # parse it so edges get a signal.
            outcome = ''
            for line in content.splitlines():
                if line.lower().startswith('outcome:'):
                    outcome = line.split(':', 1)[1].strip().lower()
                    break
            sig = outcome_signal({'outcome': outcome})

            if args.dry_run:
                log.info('dry-run memory %d: %d entities, outcome=%r sig=%.2f',
                         chunk_id, len(refs), outcome, sig)
                for r in refs:
                    log.info('    %s: %s', r.type, r.display_name)
                processed += 1
                continue

            s = upsert_entities_and_edges(
                memory_id=int(chunk_id),
                refs=refs,
                outcome=sig,
                conn=conn,
            )
            conn.commit()
            total_nodes += s['nodes_upserted']
            total_edges += s['edges_upserted']
            processed += 1
            if args.verbose:
                log.info('memory %d: %d entities, %d nodes, %d edges',
                         chunk_id, len(refs), s['nodes_upserted'],
                         s['edges_upserted'])
    finally:
        conn.close()

    runtime = time.monotonic() - t0
    log.info(
        'done: processed=%d zero-entity=%d nodes_upserted=%d '
        'edges_upserted=%d runtime=%.1fs dry_run=%s',
        processed, zero_entity_rows, total_nodes, total_edges,
        runtime, args.dry_run,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
