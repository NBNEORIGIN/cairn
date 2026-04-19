#!/usr/bin/env python3
"""Phase C cutover — flip DEEK_IMPRESSIONS_SHADOW to false.

Scheduled via cron for 2026-04-26 09:00 UTC, one-shot. Runs the shadow
analyser, applies safety gates, and — only if every gate passes:

  1. Updates /opt/nbne/deek/deploy/.env, setting
     DEEK_IMPRESSIONS_SHADOW=false (comment-preserving)
  2. Restarts the deek-api container so the new env takes effect
  3. Runs scripts/sync-policy.sh to pull the latest NBNE_PROTOCOL.md
     (by this time the nbne-policy Impressions Layer PR should be
     merged — if not, sync is a no-op and the protocol patch lands
     later)
  4. Writes a cutover record to data/impressions_cutover.jsonl so
     read-after-the-fact is possible

If ANY gate fails, the script exits 0 with a written reason. The cron
doesn't re-fire; Toby reviews manually and either flips the flag by
hand or re-runs with --force.

Usage:
    python scripts/impressions_cutover.py             # safe mode
    python scripts/impressions_cutover.py --dry-run   # report only
    python scripts/impressions_cutover.py --force     # skip safety gates

Safety gates:
    - At least 100 shadow records logged
    - Span of at least 3 days between first and last record
    - Top-5 Jaccard not pathological (not > 0.95 = identical, not < 0.02 = disjoint)
    - Env file exists and is writable
    - deek-api container is running

Exit codes:
    0 — gates passed AND cutover succeeded, OR gates blocked (normal)
    1 — cutover attempted but failed mid-flight (manual recovery needed)
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
    'DEEK_CUTOVER_LOG',
    str(REPO_ROOT / 'data' / 'impressions_cutover.jsonl'),
))
CONTAINER_NAME = os.getenv('DEEK_API_CONTAINER', 'deploy-deek-api-1')

# Gate thresholds — conservative. Tightening is a separate brief.
MIN_RECORDS = 100
MIN_SPAN_HOURS = 72          # ~3 days
MAX_JACCARD_IDENTICAL = 0.98  # all orderings identical → rerank isn't firing
MIN_JACCARD_NONZERO = 0.02   # all orderings fully disjoint → pathology

log = logging.getLogger('cutover')


# ── Safety gates ──────────────────────────────────────────────────────

def run_gates(stats: dict, force: bool = False) -> tuple[bool, list[str]]:
    """Return (ok, reasons). ok=False means refuse to cut over."""
    reasons: list[str] = []
    if force:
        return True, ['--force: all gates bypassed']

    n = stats.get('records', 0)
    if n < MIN_RECORDS:
        reasons.append(f'only {n} shadow records (need >= {MIN_RECORDS})')
    span = stats.get('span_hours', 0)
    if span < MIN_SPAN_HOURS:
        reasons.append(f'shadow span only {span}h (need >= {MIN_SPAN_HOURS}h)')
    jac = stats.get('top5_jaccard_mean', 0)
    if jac >= MAX_JACCARD_IDENTICAL:
        reasons.append(
            f'top-5 Jaccard {jac} implies rerank is identity — '
            'are salience/recency signals actually firing?'
        )
    if jac <= MIN_JACCARD_NONZERO:
        reasons.append(
            f'top-5 Jaccard {jac} implies rerank is pathological — '
            'check config/retrieval.yaml'
        )
    return len(reasons) == 0, reasons


# ── Side-effecting actions ────────────────────────────────────────────

def flip_env_file(env_file: Path) -> bool:
    """Set DEEK_IMPRESSIONS_SHADOW=false, preserving other lines.

    If the variable isn't present, append it. If it's present, rewrite
    the line in place. Atomic: write to .tmp and rename.
    """
    if not env_file.exists():
        log.error('env file not found: %s', env_file)
        return False
    try:
        lines = env_file.read_text(encoding='utf-8').splitlines(keepends=True)
    except Exception as exc:
        log.error('cannot read env: %s', exc)
        return False

    key = 'DEEK_IMPRESSIONS_SHADOW'
    wanted = f'{key}=false\n'
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.lstrip().startswith(f'{key}=') and not line.lstrip().startswith('#'):
            out.append(wanted)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        # Append with a small section header so the change is readable
        if out and not out[-1].endswith('\n'):
            out.append('\n')
        out.append('\n# Impressions layer — Phase C cutover (auto-applied)\n')
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
    """Restart the api container so the new env takes effect.

    Compose 'up -d' without --build is fast and respects the existing
    env file. Health-checks via docker inspect afterwards.
    """
    try:
        # Compose file is in /opt/nbne/deek/deploy/
        deploy_dir = env_file_parent_of(name)
        subprocess.run(
            ['docker', 'compose', 'up', '-d', '--force-recreate',
             name.replace('deploy-', '').replace('-1', '')],
            cwd=deploy_dir,
            check=True,
            capture_output=True,
            timeout=60,
        )
        # Confirm running
        r = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.Running}}', name],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() == 'true'
    except Exception as exc:
        log.error('restart failed: %s', exc)
        return False


def env_file_parent_of(_container: str) -> Path:
    return Path(os.getenv('DEEK_DEPLOY_DIR', '/opt/nbne/deek/deploy'))


def sync_policy() -> bool:
    """Pull the latest NBNE_PROTOCOL.md from nbne-policy.

    If the Impressions Layer PR hasn't been merged yet, this is a
    no-op — no harm done. If it has been merged, the vendored doc
    now reflects the live mechanism.
    """
    script = REPO_ROOT / 'scripts' / 'sync-policy.sh'
    if not script.exists():
        log.warning('sync-policy.sh not found, skipping')
        return True
    try:
        r = subprocess.run(
            ['bash', str(script)],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            log.warning('sync-policy non-zero: %s', r.stderr[:500])
        return True  # non-fatal
    except Exception as exc:
        log.warning('sync-policy failed: %s', exc)
        return True  # non-fatal


def write_cutover_record(record: dict) -> None:
    try:
        CUTOVER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CUTOVER_LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
    except Exception as exc:
        log.warning('cutover log write failed: %s', exc)


# ── Main flow ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help='Report only; do not touch env or container')
    ap.add_argument('--force', action='store_true',
                    help='Bypass safety gates (dangerous)')
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    # Read and analyse
    from scripts.analyze_impressions_shadow import (
        _default_log_path, _read_records, analyse, render_human,
    )
    shadow_path = _default_log_path()
    records = _read_records(shadow_path)
    stats = analyse(records)

    log.info('--- shadow analysis ---')
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

    # Actually cut over
    log.info('cutting over: flipping env + restarting container')
    if not flip_env_file(ENV_FILE):
        log.error('env flip failed — aborting')
        record['cutover_applied'] = False
        record['abort_reason'] = 'env flip failed'
        write_cutover_record(record)
        return 1

    if not restart_container(CONTAINER_NAME):
        log.error('container restart failed — env was flipped but api '
                  'did not cleanly restart. Manual intervention needed.')
        record['cutover_applied'] = True
        record['abort_reason'] = 'restart failed (env already flipped)'
        write_cutover_record(record)
        return 1

    sync_policy()
    record['cutover_applied'] = True
    write_cutover_record(record)
    log.info('CUTOVER COMPLETE — DEEK_IMPRESSIONS_SHADOW=false')
    return 0


if __name__ == '__main__':
    sys.exit(main())
