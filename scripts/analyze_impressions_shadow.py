#!/usr/bin/env python3
"""Analyse data/impressions_shadow.jsonl and report divergence stats.

Produces a human summary on stdout and optional JSON on stderr. Used
by the Phase C cutover script to decide whether to flip
DEEK_IMPRESSIONS_SHADOW to false, and independently runnable for
ad-hoc review.

Stats computed:

  records              total shadow records logged
  span_hours           hours from first to last record
  top1_agreement       fraction of queries where old[0].id == new[0].id
  top5_jaccard_mean    mean Jaccard(old[:5], new[:5]) over all queries
  top5_fully_disjoint  fraction of queries where old and new top-5 share NOTHING
                       (a high number means the rerank is wildly different —
                        possible pathology)
  chunk_type_distr     breakdown of what types the new ordering surfaces
  per_signal_impact    mean rel_n / sal_n / rec_n across top-1 new picks

Exit codes:
    0 — analysis completed (whether or not stats look good)
    1 — shadow log missing or unreadable

Usage:
    python scripts/analyze_impressions_shadow.py
    python scripts/analyze_impressions_shadow.py --json > report.json
    python scripts/analyze_impressions_shadow.py --log /custom/path.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def _default_log_path() -> Path:
    repo = Path(__file__).resolve().parents[1]
    return Path(
        os.getenv('DEEK_IMPRESSIONS_SHADOW_LOG',
                  str(repo / 'data' / 'impressions_shadow.jsonl'))
    )


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _top_ids(entries: list[dict], n: int = 5) -> list:
    ids = []
    for e in entries[:n]:
        cid = e.get('chunk_id')
        if cid is None:
            cid = e.get('dedupe_key')
        ids.append(cid)
    return ids


def _jaccard(a: list, b: list) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def analyse(records: list[dict]) -> dict:
    """Compute the summary stats dict."""
    n = len(records)
    if n == 0:
        return {'records': 0}

    # Timing
    ts = []
    for r in records:
        t = r.get('ts')
        if t:
            try:
                ts.append(datetime.fromisoformat(t.replace('Z', '+00:00')))
            except Exception:
                pass
    span_hours = 0.0
    if len(ts) >= 2:
        span = max(ts) - min(ts)
        span_hours = span.total_seconds() / 3600.0

    # Agreement
    top1_match = 0
    jaccards: list[float] = []
    fully_disjoint = 0
    for r in records:
        old = _top_ids(r.get('old_top') or [])
        new = _top_ids(r.get('new_top') or [])
        if old and new and old[0] == new[0]:
            top1_match += 1
        j = _jaccard(old, new)
        jaccards.append(j)
        if j == 0.0:
            fully_disjoint += 1

    # Chunk types surfaced by new ordering
    type_counter: Counter = Counter()
    for r in records:
        for e in (r.get('new_top') or [])[:1]:
            t = e.get('chunk_type')
            if t:
                type_counter[t] += 1

    # Signal impact — mean rel_n / sal_n / rec_n at new top-1
    rel_list, sal_list, rec_list, final_list = [], [], [], []
    for r in records:
        debug = r.get('debug') or []
        if not debug:
            continue
        d = debug[0]
        try:
            rel_list.append(float(d.get('rel_n', 0)))
            sal_list.append(float(d.get('sal_n', 0)))
            rec_list.append(float(d.get('rec_n', 0)))
            final_list.append(float(d.get('final', 0)))
        except Exception:
            continue

    return {
        'records': n,
        'first_ts': ts[0].isoformat() if ts else None,
        'last_ts': ts[-1].isoformat() if ts else None,
        'span_hours': round(span_hours, 2),
        'top1_agreement': round(top1_match / n, 3),
        'top5_jaccard_mean': round(statistics.mean(jaccards), 3) if jaccards else 0.0,
        'top5_fully_disjoint': round(fully_disjoint / n, 3),
        'new_top1_chunk_type_distribution': dict(type_counter.most_common()),
        'mean_relevance_normalised_top1': (
            round(statistics.mean(rel_list), 3) if rel_list else None
        ),
        'mean_salience_normalised_top1': (
            round(statistics.mean(sal_list), 3) if sal_list else None
        ),
        'mean_recency_normalised_top1': (
            round(statistics.mean(rec_list), 3) if rec_list else None
        ),
        'mean_final_score_top1': (
            round(statistics.mean(final_list), 3) if final_list else None
        ),
    }


def render_human(stats: dict) -> str:
    if not stats or stats.get('records', 0) == 0:
        return 'No shadow records. Is DEEK_IMPRESSIONS_SHADOW=true and retrieval happening?'

    lines = []
    lines.append(f"Records logged:          {stats['records']}")
    lines.append(f"First seen:              {stats['first_ts']}")
    lines.append(f"Last seen:               {stats['last_ts']}")
    lines.append(f"Time span:               {stats['span_hours']}h")
    lines.append('')
    lines.append(f"Top-1 agreement:         {stats['top1_agreement'] * 100:.1f}%")
    lines.append(f"Top-5 Jaccard (mean):    {stats['top5_jaccard_mean']:.3f}")
    lines.append(f"Top-5 fully disjoint:    {stats['top5_fully_disjoint'] * 100:.1f}%")
    lines.append('')
    lines.append(f"Mean relevance (top-1):  {stats['mean_relevance_normalised_top1']}")
    lines.append(f"Mean salience  (top-1):  {stats['mean_salience_normalised_top1']}")
    lines.append(f"Mean recency   (top-1):  {stats['mean_recency_normalised_top1']}")
    lines.append(f"Mean final     (top-1):  {stats['mean_final_score_top1']}")
    lines.append('')
    lines.append('New top-1 chunk_type distribution:')
    for t, n in (stats.get('new_top1_chunk_type_distribution') or {}).items():
        lines.append(f"    {t:20s}  {n}")

    # Flag pathologies for humans scanning the output
    warnings = []
    if stats['top5_fully_disjoint'] > 0.5:
        warnings.append(
            'WARNING: more than 50% of queries return entirely different top-5.'
            ' The rerank may be over-weighting salience/recency — review '
            'config/retrieval.yaml before cutover.'
        )
    if stats['top1_agreement'] < 0.2:
        warnings.append(
            'WARNING: top-1 agreement below 20%. Either the rerank is '
            'highly effective, or something is broken.'
        )
    if warnings:
        lines.append('')
        for w in warnings:
            lines.append(w)

    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--log', type=str, default=None,
                    help='Override shadow log path')
    ap.add_argument('--json', action='store_true',
                    help='Emit JSON to stdout instead of human summary')
    args = ap.parse_args()

    path = Path(args.log) if args.log else _default_log_path()
    if not path.exists():
        print(f'No shadow log at {path}', file=sys.stderr)
        return 1

    records = _read_records(path)
    stats = analyse(records)

    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(render_human(stats))
    return 0


if __name__ == '__main__':
    sys.exit(main())
