"""
Telegram notifier for new pending drafts in the Cairn inbox.

Runs as a cron job every few minutes. Scans
``cairn_intel.email_triage`` for rows that have a draft, haven't
been reviewed, and haven't been notified yet — fires a Telegram
ping to the registered user with a link straight to the inbox
detail view.

Phase 2 of the active-PM workflow (2026-05-13). Telegram chat IDs
live in ``cairn_intel.registered_telegram_chats`` — set up in April
via the bot's /register flow. Toby's chat is already there.

Quiet-hours: skips between 22:00 and 07:00 UTC by default. Override
with ``DEEK_INBOX_NOTIFY_QUIET_HOURS=23-06`` to widen the window.

Run:
  docker exec -w /app -e PYTHONPATH=/app deploy-deek-api-1 \\
    python scripts/notify_inbox_drafts.py
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path

CLAW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAW_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(CLAW_ROOT / '.env')
except Exception:
    pass

logger = logging.getLogger('notify_inbox_drafts')

# Who to notify. Keyed by user email — looked up against
# cairn_intel.registered_telegram_chats. Default = Toby's primary.
NOTIFY_USER_EMAIL = os.getenv(
    'DEEK_INBOX_NOTIFY_USER', 'toby@nbnesigns.com',
)

# Don't fire pings between these UTC hours. Format "HH-HH".
# Default 22-07 = 10pm to 7am UTC.
_DEFAULT_QUIET = '22-07'


def _quiet_now() -> bool:
    raw = (os.getenv('DEEK_INBOX_NOTIFY_QUIET_HOURS') or _DEFAULT_QUIET).strip()
    try:
        start_s, end_s = raw.split('-', 1)
        start_h = int(start_s)
        end_h = int(end_s)
    except Exception:
        return False
    now_h = datetime.now(timezone.utc).hour
    if start_h <= end_h:
        return start_h <= now_h < end_h
    # Window wraps midnight (e.g. 22-07)
    return now_h >= start_h or now_h < end_h


def _format_ping(row: dict, project_name: str | None) -> str:
    sender = (row.get('email_sender') or '?')[:60]
    subject = (row.get('email_subject') or '(no subject)')[:80]
    proj = project_name or '(unmapped)'
    draft_preview = (row.get('draft_reply') or '').strip()
    # Markdown-safe: escape underscores and asterisks in the dynamic
    # parts. Lightweight — full markdown escaping is overkill here.
    def safe(s: str) -> str:
        return s.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[')
    preview = draft_preview.replace('\n', ' ')[:200]
    if len(draft_preview) > 200:
        preview += '…'
    url = f'https://deek.nbnesigns.co.uk/voice/inbox'
    return (
        f'📬 *New draft for {safe(proj)}*\n'
        f'From: {safe(sender)}\n'
        f'Subject: {safe(subject)}\n\n'
        f'_{safe(preview)}_\n\n'
        f'→ {url}'
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s notify_inbox_drafts — %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    if _quiet_now():
        logger.info('quiet hours — skipping')
        return 0

    import psycopg2
    from psycopg2.extras import RealDictCursor
    from core.channels.nudge import _send_telegram, _lookup_chat_id

    conn = psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=5)
    try:
        chat_id = _lookup_chat_id(conn, NOTIFY_USER_EMAIL)
        if not chat_id:
            logger.warning(
                'no registered Telegram chat for %s — skipping. '
                'Register via the bot /register flow first.',
                NOTIFY_USER_EMAIL,
            )
            return 0
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, email_sender, email_subject, project_id,
                       draft_reply, processed_at
                  FROM cairn_intel.email_triage
                 WHERE inbox_notified_at IS NULL
                   AND reviewed_at IS NULL
                   AND draft_reply IS NOT NULL AND draft_reply <> ''
                   AND processed_at > NOW() - INTERVAL '24 hours'
                 ORDER BY processed_at ASC
                 LIMIT 50
                """,
            )
            rows = cur.fetchall()
        if not rows:
            logger.info('no new drafts to notify')
            return 0
        logger.info('notifying %d new draft(s)', len(rows))

        # Per-project name cache to avoid repeat CRM lookups in one run
        from core.triage.inbox import _project_name
        project_name_cache: dict[str, str] = {}

        sent = 0
        for row in rows:
            pid = row.get('project_id')
            if pid and pid not in project_name_cache:
                project_name_cache[pid] = _project_name(pid) or ''
            proj = project_name_cache.get(pid) if pid else None

            text = _format_ping(dict(row), proj)
            ok, msg_id, err = _send_telegram(chat_id, text)
            if not ok:
                logger.warning(
                    'telegram send failed for triage %s: %s',
                    row['id'], err,
                )
                # Don't mark notified — we'll retry next run
                continue
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE cairn_intel.email_triage SET inbox_notified_at = NOW() WHERE id = %s',
                    (row['id'],),
                )
                conn.commit()
            sent += 1
            logger.info('notified draft #%d (telegram msg_id=%s)', row['id'], msg_id)
        logger.info('done — %d sent', sent)
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
