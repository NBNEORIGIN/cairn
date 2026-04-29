"""Jo's mailbox processor — runs on Rex (jo-pip) only.

Polls jo@nbnesigns.com via IMAP every 15 minutes, ingests + embeds new
messages into Rex's isolated Postgres. Mirrors scripts/process_deek_inbox.py
(which handles cairn@ on Hetzner) but scoped to Jo's mailbox + Rex's
database.

Privacy boundary: Jo's email content writes to jo-pip's `cairn_email_raw`
+ `claw_code_chunks` only. It never crosses to NBNE-Deek — that's
enforced by the DATABASE_URL env on the jo-pip-api container, which
points at the local jo-pip-db container (separate from Hetzner's
deploy-deek-db).

Cron (on nbne1):
    */15 * * * * docker exec -w /app -e PYTHONPATH=/app jo-pip-api \\
        python scripts/process_jo_inbox.py >> /opt/nbne/jo-pip/logs/jo-inbox.log 2>&1

Required env on jo-pip-api:
    IMAP_PASSWORD_JO  — Jo's IONOS mailbox password
    IMAP_HOST         — defaults to imap.ionos.co.uk if unset

Exit codes:
    0 — completed (zero or more messages ingested)
    1 — fatal error (DB unreachable, IMAP creds missing, etc.)
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# .env load is best-effort — in the jo-pip-api container the env is
# already populated by docker compose, but we keep this for local dev.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / '.env')
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s',
)
logger = logging.getLogger('jo_inbox_processor')


def main() -> int:
    logger.info('jo@ inbox processor starting at %s', datetime.utcnow().isoformat())

    try:
        from core.email_ingest.db import ensure_schema
        ensure_schema()
    except Exception as exc:
        logger.error('schema setup failed: %s', exc)
        return 1

    try:
        from core.email_ingest.processor import process_inbox
        result = process_inbox(mailbox='jo', embed_immediately=True)
        logger.info('result: %s', json.dumps(result, default=str))
    except Exception as exc:
        logger.exception('inbox processor failed: %s', exc)
        return 1

    logger.info('jo@ inbox processor finished at %s', datetime.utcnow().isoformat())
    return 0


if __name__ == '__main__':
    sys.exit(main())
