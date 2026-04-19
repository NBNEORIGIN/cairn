#!/usr/bin/env python3
"""Dream-state daily maintenance — Brief 4 Phase C.

Runs once a day after the nocturnal loop has had its chance. Does
three things:

    1. Stale-candidate sweep (Task 9). Candidates that have been
       surfaced for >= STALE_DAYS without a review action are marked
       'expired' so the morning briefing doesn't keep showing them.
       If >EXPIRED_ALERT_RATE of the week's candidates expired, the
       digest flags the issue — either the briefing isn't being
       read or the filter is too permissive.
    2. Schema decay (Task 10). Active schemas not accessed in
       DORMANT_AFTER_DAYS → dormant. Dormant schemas not accessed in
       ARCHIVED_AFTER_DAYS → archived. Retrieval can still surface
       dormant schemas at reduced weight; reinforcement on access
       re-activates them.
    3. Daily digest (Task 12). Prints a summary to stdout and —
       if SMTP_* env vars are configured — emails it to Toby. No
       Postmark SDK needed; the shared SMTP path already works.

Idempotent. Exit 0 even when nothing happened (zero-candidate days
are normal). Exit 1 only on fatal setup errors (DB unreachable).

Usage:
    python scripts/dream_maintenance.py           # full run + email
    python scripts/dream_maintenance.py --dry-run # report only
    python scripts/dream_maintenance.py --no-email
"""
from __future__ import annotations

import argparse
import logging
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

STALE_DAYS = 7
EXPIRED_ALERT_RATE = 0.5
DORMANT_AFTER_DAYS = 90
ARCHIVED_AFTER_DAYS = 180

DIGEST_TO = os.getenv('DEEK_DREAM_DIGEST_TO', 'toby@nbnesigns.com')


log = logging.getLogger('dream-maintenance')


# ── DB helpers ────────────────────────────────────────────────────────

def _db_url() -> str:
    u = os.getenv('DATABASE_URL', '')
    if not u:
        raise RuntimeError('DATABASE_URL not set')
    return u


def _connect():
    import psycopg2
    return psycopg2.connect(_db_url(), connect_timeout=5)


# ── Sweep + decay ─────────────────────────────────────────────────────

def sweep_stale_candidates(conn, dry_run: bool) -> dict:
    """Mark candidates surfaced >= STALE_DAYS ago without review as
    expired. Returns counts for the digest.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM dream_candidates
                WHERE reviewed_at IS NULL
                  AND surfaced_at IS NOT NULL
                  AND generated_at < NOW() - (INTERVAL '1 day' * %s)""",
            (STALE_DAYS,),
        )
        (to_expire,) = cur.fetchone()

        # Also count total surfaced in the last week for the rate.
        cur.execute(
            """SELECT COUNT(*) FROM dream_candidates
                WHERE surfaced_at IS NOT NULL
                  AND generated_at > NOW() - INTERVAL '7 days'""",
        )
        (total_recent,) = cur.fetchone()

        if not dry_run and to_expire:
            cur.execute(
                """UPDATE dream_candidates
                      SET review_action = 'expired',
                          reviewed_at = NOW()
                    WHERE reviewed_at IS NULL
                      AND surfaced_at IS NOT NULL
                      AND generated_at < NOW() - (INTERVAL '1 day' * %s)""",
                (STALE_DAYS,),
            )
            conn.commit()
    expired_rate = (
        float(to_expire) / float(total_recent) if total_recent else 0.0
    )
    return {
        'expired': int(to_expire),
        'recent_surfaced': int(total_recent),
        'expired_rate': round(expired_rate, 3),
        'alert': expired_rate > EXPIRED_ALERT_RATE,
    }


def decay_schemas(conn, dry_run: bool) -> dict:
    """Transition schemas: active→dormant after 90d idle, dormant→archived
    after 180d idle. Reactivation-on-access is handled in the
    retrieval path; this is the decay half of the lifecycle.
    """
    summary = {'to_dormant': 0, 'to_archived': 0}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM schemas
                WHERE status = 'active'
                  AND last_accessed_at < NOW() - (INTERVAL '1 day' * %s)""",
            (DORMANT_AFTER_DAYS,),
        )
        (to_dormant,) = cur.fetchone()
        summary['to_dormant'] = int(to_dormant)

        cur.execute(
            """SELECT COUNT(*) FROM schemas
                WHERE status = 'dormant'
                  AND last_accessed_at < NOW() - (INTERVAL '1 day' * %s)""",
            (ARCHIVED_AFTER_DAYS,),
        )
        (to_archived,) = cur.fetchone()
        summary['to_archived'] = int(to_archived)

        if not dry_run:
            if to_dormant:
                cur.execute(
                    """UPDATE schemas SET status = 'dormant'
                        WHERE status = 'active'
                          AND last_accessed_at < NOW() - (INTERVAL '1 day' * %s)""",
                    (DORMANT_AFTER_DAYS,),
                )
            if to_archived:
                cur.execute(
                    """UPDATE schemas SET status = 'archived'
                        WHERE status = 'dormant'
                          AND last_accessed_at < NOW() - (INTERVAL '1 day' * %s)""",
                    (ARCHIVED_AFTER_DAYS,),
                )
            conn.commit()
    return summary


def last_nights_stats(conn) -> dict:
    """Return counts for the digest: generated, surfaced, action totals."""
    with conn.cursor() as cur:
        # The most recent generated_at date
        cur.execute("SELECT MAX(generated_at)::date FROM dream_candidates")
        (latest_date,) = cur.fetchone()
        if latest_date is None:
            return {'latest_date': None}

        cur.execute(
            """SELECT COUNT(*),
                      COUNT(*) FILTER (WHERE surfaced_at IS NOT NULL),
                      COUNT(*) FILTER (WHERE review_action = 'accepted'),
                      COUNT(*) FILTER (WHERE review_action = 'rejected'),
                      COUNT(*) FILTER (WHERE review_action = 'deferred'),
                      COUNT(*) FILTER (WHERE review_action = 'expired')
                 FROM dream_candidates
                WHERE generated_at::date = %s""",
            (latest_date,),
        )
        row = cur.fetchone()
    return {
        'latest_date': latest_date.isoformat(),
        'total': int(row[0]),
        'surfaced': int(row[1]),
        'accepted': int(row[2]),
        'rejected': int(row[3]),
        'deferred': int(row[4]),
        'expired': int(row[5]),
    }


def schema_totals(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT status, COUNT(*) FROM schemas
                GROUP BY status"""
        )
        counts = {r[0]: int(r[1]) for r in cur.fetchall()}
    return {
        'active': int(counts.get('active', 0)),
        'dormant': int(counts.get('dormant', 0)),
        'archived': int(counts.get('archived', 0)),
    }


# ── Digest ────────────────────────────────────────────────────────────

def format_digest(
    sweep: dict, decay: dict, last_night: dict, totals: dict,
) -> str:
    lines: list[str] = []
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    lines.append(f'Deek dream-state digest — {today}')
    lines.append('=' * 60)
    lines.append('')

    if last_night.get('latest_date'):
        lines.append(f"Last night's run ({last_night['latest_date']}):")
        lines.append(f"  candidates generated: {last_night['total']}")
        lines.append(f"  surfaced:             {last_night['surfaced']}")
        if any(last_night.get(k, 0) for k in ('accepted', 'rejected', 'deferred', 'expired')):
            lines.append(
                f"  actions so far:       "
                f"{last_night.get('accepted', 0)} accepted · "
                f"{last_night.get('rejected', 0)} rejected · "
                f"{last_night.get('deferred', 0)} deferred · "
                f"{last_night.get('expired', 0)} expired"
            )
    else:
        lines.append('No nocturnal runs on record yet.')
    lines.append('')

    lines.append('Stale-candidate sweep:')
    lines.append(
        f"  expired this run: {sweep['expired']} "
        f"(of {sweep['recent_surfaced']} surfaced in last 7 days = "
        f"{sweep['expired_rate'] * 100:.1f}%)"
    )
    if sweep['alert']:
        lines.append(
            '  ⚠  EXPIRED RATE > 50% — either the briefing isn\'t being '
            'read, or the filter is too permissive. Tune weights or '
            'curate more anti-patterns.'
        )
    lines.append('')

    lines.append('Schema lifecycle:')
    lines.append(
        f"  active:   {totals['active']}   "
        f"dormant: {totals['dormant']}   "
        f"archived: {totals['archived']}"
    )
    if decay['to_dormant'] or decay['to_archived']:
        lines.append(
            f"  transitioned this run: "
            f"{decay['to_dormant']} → dormant, "
            f"{decay['to_archived']} → archived"
        )
    lines.append('')
    lines.append('— Deek')
    return '\n'.join(lines)


def smtp_config() -> dict | None:
    host = os.getenv('SMTP_HOST', '').strip()
    user = os.getenv('SMTP_USER', '').strip()
    password = os.getenv('SMTP_PASS', '').strip()
    if not (host and user and password):
        return None
    try:
        port = int(os.getenv('SMTP_PORT', '587').strip())
    except ValueError:
        port = 587
    return {
        'host': host,
        'port': port,
        'user': user,
        'password': password,
        'from_addr': os.getenv('SMTP_FROM', 'deek@nbnesigns.com'),
    }


def send_digest(cfg: dict, to_addr: str, body: str) -> None:
    msg = EmailMessage()
    msg['Subject'] = 'Deek dream-state digest'
    msg['From'] = cfg['from_addr']
    msg['To'] = to_addr
    msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(cfg['host'], cfg['port'], timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(cfg['user'], cfg['password'])
        server.send_message(msg)


# ── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help='Report only; do not sweep or decay')
    ap.add_argument('--no-email', action='store_true',
                    help='Skip the digest email (always prints to stdout)')
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    try:
        conn = _connect()
    except Exception as exc:
        log.error('db connect failed: %s', exc)
        return 1

    try:
        sweep = sweep_stale_candidates(conn, dry_run=args.dry_run)
        decay = decay_schemas(conn, dry_run=args.dry_run)
        last_night = last_nights_stats(conn)
        totals = schema_totals(conn)
    finally:
        conn.close()

    body = format_digest(sweep, decay, last_night, totals)
    print(body)

    if args.no_email:
        return 0
    cfg = smtp_config()
    if cfg is None:
        log.info('SMTP not configured — skipping email (printed to stdout only)')
        return 0
    try:
        send_digest(cfg, DIGEST_TO, body)
        log.info('digest emailed to %s', DIGEST_TO)
    except Exception as exc:
        log.warning('digest email failed (non-fatal): %s', exc)

    return 0


if __name__ == '__main__':
    sys.exit(main())
