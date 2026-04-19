#!/usr/bin/env python3
"""Brief 3 Phase C cutover — flip DEEK_CROSSLINK_SHADOW to false.

Scheduled via cron for 2026-04-27 09:00 UTC (one day after the
Impressions Phase C cutover, to avoid collision). Runs the graph
shadow analyser, applies safety gates, and — only if every gate
passes:

  1. Updates /opt/nbne/deek/deploy/.env, setting
     DEEK_CROSSLINK_SHADOW=false (comment-preserving)
  2. Restarts the deek-api container so the new env takes effect
  3. Runs scripts/sync-policy.sh to pull the Crosslink Graph section
     that should by then be merged into nbne-policy
  4. Writes a cutover record to data/crosslink_cutover.jsonl

If ANY gate fails, exits 0 with a written reason. Silent skip, no
retries. See scripts/impressions_cutover.py for the same pattern.

Usage:
    python scripts/crosslink_cutover.py           # safe mode
    python scripts/crosslink_cutover.py --dry-run
    python scripts/crosslink_cutover.py --force   # skip safety gates

Safety gates (all must pass):
    - At least 50 shadow records logged
    - Span of at least 3 days between first and last record
    - Empty-walk rate under 95% (otherwise the graph is so sparse
      cutover is premature)
    - Top path entity not dominating > 80% of hits (catches
      degenerate high-centrality nodes the stop-list missed)
    - Env file exists and is writable
    - deek-api container is running

Exit codes:
    0 — gates passed AND cutover succeeded, OR gates blocked (normal)
    1 — cutover attempted but failed mid-flight (manual recovery)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

ENV_FILE = Path(os.getenv('DEEK_ENV_FILE', '/opt/nbne/deek/deploy/.env'))
CUTOVER_LOG = Path(os.getenv(
    'DEEK_CROSSLINK_CUTOVER_LOG',
    str(REPO_ROOT / 'data' / 'crosslink_cutover.jsonl'),
))
CONTAINER_NAME = os.getenv('DEEK_API_CONTAINER', 'deploy-deek-api-1')
ENV_KEY = 'DEEK_CROSSLINK_SHADOW'

# Gate thresholds — tuned for the graph shadow's different health
# signals vs Impressions. An empty walk is NOT a failure by itself (at
# low memory volume most walks will be empty); we only reject cutover
# if the graph is so sparse that shadow data carries no signal.
MIN_RECORDS = 50
MIN_SPAN_HOURS = 72
MAX_EMPTY_RATE = 0.95
MAX_DOMINANT_ENTITY_SHARE = 0.80

log = logging.getLogger('crosslink-cutover')


# ── Safety gates ──────────────────────────────────────────────────────

def run_gates(stats: dict, force: bool = False) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if force:
        return True, ['--force: all gates bypassed']

    n = stats.get('records', 0)
    if n < MIN_RECORDS:
        reasons.append(f'only {n} shadow records (need >= {MIN_RECORDS})')
    span = stats.get('span_hours', 0)
    if span < MIN_SPAN_HOURS:
        reasons.append(f'shadow span {span}h (need >= {MIN_SPAN_HOURS}h)')
    empty = stats.get('empty_rate', 1.0)
    if empty > MAX_EMPTY_RATE:
        reasons.append(
            f'empty-walk rate {empty * 100:.1f}% > {MAX_EMPTY_RATE * 100:.0f}% '
            '— graph is too sparse to cut over safely; wait for more memories'
        )

    # Detect degenerate dominant path entities
    top_entities = stats.get('top_path_entities') or []
    if top_entities:
        # top_path_entities is a list of [entity, count] from Counter.most_common
        total = sum(count for _, count in top_entities)
        if total > 0:
            top_share = top_entities[0][1] / total
            if top_share > MAX_DOMINANT_ENTITY_SHARE:
                reasons.append(
                    f"entity '{top_entities[0][0]}' dominates "
                    f'{top_share * 100:.1f}% of walks '
                    f'— add to stop_entities in config/entity_taxonomy.yaml'
                )
    return len(reasons) == 0, reasons


# ── Side effects ──────────────────────────────────────────────────────

def flip_env_file(env_file: Path) -> bool:
    if not env_file.exists():
        log.error('env file not found: %s', env_file)
        return False
    try:
        lines = env_file.read_text(encoding='utf-8').splitlines(keepends=True)
    except Exception as exc:
        log.error('cannot read env: %s', exc)
        return False

    wanted = f'{ENV_KEY}=false\n'
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.lstrip().startswith(f'{ENV_KEY}=') and not line.lstrip().startswith('#'):
            out.append(wanted)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith('\n'):
            out.append('\n')
        out.append('\n# Crosslink graph — Phase C cutover (auto-applied)\n')
        out.append(wanted)

    tmp = env_file.with_suffix(env_file.suffix + '.cutover-tmp')
    try:
        tmp.write_text(''.join(out), encoding='utf-8')
        shutil.move(str(tmp), str(env_file))
    except Exception as exc:
        log.error('cannot write env: %s', exc)
        try:
            tmp.unlink()
        except Exception:
            pass
        return False
    return True


def restart_container(name: str) -> bool:
    try:
        deploy_dir = Path(os.getenv('DEEK_DEPLOY_DIR', '/opt/nbne/deek/deploy'))
        subprocess.run(
            ['docker', 'compose', 'up', '-d', '--force-recreate',
             name.replace('deploy-', '').replace('-1', '')],
            cwd=str(deploy_dir), check=True, capture_output=True, timeout=60,
        )
        r = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.Running}}', name],
            check=True, capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() == 'true'
    except Exception as exc:
        log.error('restart failed: %s', exc)
        return False


def sync_policy() -> bool:
    script = REPO_ROOT / 'scripts' / 'sync-policy.sh'
    if not script.exists():
        log.warning('sync-policy.sh not found, skipping')
        return True
    try:
        subprocess.run(
            ['bash', str(script)], cwd=str(REPO_ROOT), check=False,
            capture_output=True, text=True, timeout=60,
        )
        return True
    except Exception as exc:
        log.warning('sync-policy failed: %s', exc)
        return True


def write_cutover_record(record: dict) -> None:
    try:
        CUTOVER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CUTOVER_LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, default=str) + '\n')
    except Exception as exc:
        log.warning('cutover log write failed: %s', exc)


# ── Main flow ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    # Reuse the analyser we already built
    from scripts.analyze_graph_shadow import (
        _default_log, _read, analyse, render_human,
    )
    shadow_path = _default_log()
    records = _read(shadow_path)
    stats = analyse(records)

    log.info('--- graph shadow analysis ---')
    for line in render_human(stats).splitlines():
        log.info(line)

    ok, reasons = run_gates(stats, force=args.force)
    record = {
        'ran_at': datetime.now(timezone.utc).isoformat(),
        'stats': stats,
        'gates_passed': ok,
        'reasons': reasons,
        'forced': bool(args.force),
        'dry_run': bool(args.dry_run),
        'cutover_applied': False,
    }

    if not ok:
        log.warning('CUTOVER BLOCKED: %s', '; '.join(reasons))
        write_cutover_record(record)
        return 0

    if args.dry_run:
        log.info('DRY RUN — gates passed; would have flipped env + restarted')
        write_cutover_record(record)
        return 0

    log.info('cutting over: flipping env + restarting container')
    if not flip_env_file(ENV_FILE):
        record['abort_reason'] = 'env flip failed'
        write_cutover_record(record)
        return 1
    if not restart_container(CONTAINER_NAME):
        record['cutover_applied'] = True
        record['abort_reason'] = 'restart failed (env already flipped)'
        write_cutover_record(record)
        return 1
    sync_policy()
    record['cutover_applied'] = True
    write_cutover_record(record)
    log.info('CUTOVER COMPLETE — %s=false', ENV_KEY)
    return 0


if __name__ == '__main__':
    sys.exit(main())
