"""
Standalone AMI SP-API sync runner.

Called by Windows Scheduled Task every 6 hours, independent of the FastAPI
process. Uses the same scheduler.py logic as the API endpoint but does not
require the API to be running.

Usage:
    D:\claw\.venv\Scripts\python.exe D:\claw\scripts\run_ami_sync.py
    D:\claw\.venv\Scripts\python.exe D:\claw\scripts\run_ami_sync.py --force
"""
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Resolve D:\claw as the working root regardless of where we're called from
CLAW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAW_ROOT))

# Load .env before any imports that read env vars
from dotenv import load_dotenv
load_dotenv(CLAW_ROOT / '.env')

# Logging — write to same logs/api dir so NSSM log rotation covers it
log_dir = CLAW_ROOT / 'logs' / 'ami_sync'
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / 'ami_sync.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger('ami_sync_runner')


def main():
    force = '--force' in sys.argv
    logger.info('AMI sync starting (force=%s)', force)

    try:
        from core.amazon_intel.db import ensure_schema
        ensure_schema()
        logger.info('Schema verified')
    except Exception as exc:
        logger.error('Schema setup failed: %s', exc)
        sys.exit(1)

    try:
        from core.amazon_intel.spapi.scheduler import run_full_sync
        result = run_full_sync(force=force)
        logger.info('Sync complete: %s', json.dumps(result, indent=2, default=str))
    except Exception as exc:
        logger.exception('Sync failed: %s', exc)
        sys.exit(1)

    logger.info('AMI sync finished at %s', datetime.utcnow().isoformat())


if __name__ == '__main__':
    main()
