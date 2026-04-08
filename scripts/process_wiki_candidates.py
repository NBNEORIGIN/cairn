"""
Cairn wiki candidate processor — run by Windows Scheduled Task every 20 minutes.

Processes all wiki_candidate emails in cairn_email_raw that haven't yet been
turned into wiki articles. Writes articles to wiki/modules/ and embeds them.

Usage:
    D:\claw\.venv\Scripts\python.exe D:\claw\scripts\process_wiki_candidates.py

Registered by: scripts\install_scheduled_tasks.ps1 (CairnWikiCandidates task)
"""
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

CLAW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAW_ROOT))

from dotenv import load_dotenv
load_dotenv(CLAW_ROOT / '.env')

log_dir = CLAW_ROOT / 'logs' / 'wiki_gen'
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / 'wiki_candidates.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger('process_wiki_candidates')


def main():
    logger.info('Wiki candidate processor starting at %s', datetime.utcnow().isoformat())

    try:
        from core.wiki_gen.db import ensure_schema
        ensure_schema()
    except Exception as exc:
        logger.error('Schema setup failed: %s', exc)
        sys.exit(1)

    try:
        from core.wiki_gen.processor import process_wiki_candidates
        result = process_wiki_candidates()
        logger.info('Result: %s', json.dumps(result, default=str))
    except Exception as exc:
        logger.exception('Wiki candidate processor failed: %s', exc)
        sys.exit(1)

    logger.info('Wiki candidate processor finished at %s', datetime.utcnow().isoformat())


if __name__ == '__main__':
    main()
