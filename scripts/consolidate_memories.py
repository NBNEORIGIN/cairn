#!/usr/bin/env python3
"""Nightly memory consolidation entry point — invoked by Hetzner cron.

Runs at 02:00 UTC daily per the crontab entry documented in
docs/IMPRESSIONS.md. A single pass samples recent high-salience
memories, clusters them, asks the local Ollama model to distil each
cluster into a pattern, and writes survivors to the `schemas` table.

Cost: zero cloud calls. All inference through OLLAMA_BASE_URL which
resolves to deek-gpu via Tailscale.

Usage:
    python scripts/consolidate_memories.py               # defaults
    python scripts/consolidate_memories.py --window 7    # shorter window
    python scripts/consolidate_memories.py --dry-run     # no DB writes

Exit codes:
    0 — ran to completion (even if zero schemas were written — that's
        normal on sparse-memory days)
    1 — fatal error that prevented the run from starting (DB down etc.)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--window', type=int, default=30,
                    help='Window in days (default: 30)')
    ap.add_argument('--candidates', type=int, default=50,
                    help='Top-N candidates to consider (default: 50)')
    ap.add_argument('--max-schemas', type=int, default=10,
                    help='Stop after writing N schemas (default: 10)')
    ap.add_argument('--model', type=str, default=None,
                    help='Override Ollama model')
    ap.add_argument('--dry-run', action='store_true',
                    help='Log what would happen, do not write schemas')
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    log = logging.getLogger('consolidate')

    if args.dry_run:
        # Import and run only up to the LLM-call step, printing what
        # would be done. Implementation reuses the sampling + clustering
        # helpers without touching the `schemas` table.
        from core.memory.consolidation import (
            sample_candidates, cluster_candidates,
        )
        cands = sample_candidates(args.window, args.candidates)
        log.info('would consider %d candidates', len(cands))
        clusters = cluster_candidates(cands)
        log.info('would form %d clusters of >= %d',
                 len(clusters), 3)
        for i, cluster in enumerate(clusters, 1):
            ids = [c.chunk_id for c in cluster]
            log.info('  cluster %d: n=%d, avg_salience=%.2f, ids=%s',
                     i, len(cluster),
                     sum(c.salience for c in cluster) / len(cluster),
                     ids)
        return 0

    from core.memory.consolidation import consolidate_recent_memories
    try:
        run = consolidate_recent_memories(
            window_days=args.window,
            candidate_limit=args.candidates,
            max_schemas=args.max_schemas,
            model=args.model,
        )
    except Exception as exc:
        log.exception('consolidation crashed: %s', exc)
        return 1

    log.info(
        'done: candidates=%d clusters=%d llm_calls=%d schemas_written=%d '
        'skipped(dedup=%d conf=%d ground=%d empty=%d) runtime=%.1fs errors=%d',
        run.candidates_considered, run.clusters_formed, run.llm_calls,
        run.schemas_written, run.schemas_skipped_dedup,
        run.schemas_skipped_confidence, run.schemas_skipped_grounding,
        run.schemas_skipped_empty, run.runtime_seconds, len(run.errors),
    )
    if run.errors:
        for err in run.errors[:5]:
            log.warning('error: %s', err)
    return 0


if __name__ == '__main__':
    sys.exit(main())
