"""Postgres migration bootstrapper.

Applies numbered SQL files in migrations/postgres/ in lexicographic
order. Records each successful apply in `schema_migrations` so the
same file never runs twice. Invoked at API startup (api/main.py
lifespan) and runnable standalone via `python -m core.memory.migrations`.

Philosophy:
- No ORM, no migration framework.
- Each SQL file is idempotent. If it runs twice despite us, nothing
  should break (we rely on `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`
  idioms).
- On failure, log loudly and DO NOT mark the file as applied. The next
  boot retries.

See migrations/postgres/README.md.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = Path(
    os.getenv('DEEK_MIGRATIONS_DIR', str(_REPO_ROOT / 'migrations' / 'postgres'))
)


_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sha256 TEXT NOT NULL
);
"""


def _sha256_of(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _connect():
    import psycopg2
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        raise RuntimeError('DATABASE_URL not set — cannot run migrations')
    return psycopg2.connect(db_url, connect_timeout=5)


def apply_migrations() -> dict:
    """Apply any unapplied migrations. Returns a summary dict.

    Safe to call multiple times per process lifetime. Returns:
        {
          'applied': [filenames...],
          'skipped': [filenames...],
          'total': N,
          'errors': [{filename, error}, ...]
        }

    Never raises — errors are captured and returned. The caller decides
    whether to bail at startup (api/main.py logs but keeps going if a
    migration fails, matching the existing "warn and continue" pattern
    for optional subsystems).
    """
    summary: dict = {'applied': [], 'skipped': [], 'total': 0, 'errors': []}

    if not MIGRATIONS_DIR.exists():
        logger.warning('[migrations] %s does not exist; nothing to do',
                       MIGRATIONS_DIR)
        return summary

    files = sorted(p for p in MIGRATIONS_DIR.glob('*.sql') if p.is_file())
    summary['total'] = len(files)
    if not files:
        return summary

    try:
        conn = _connect()
    except Exception as exc:
        summary['errors'].append({'filename': '(connect)', 'error': str(exc)})
        logger.error('[migrations] cannot connect: %s', exc)
        return summary

    try:
        with conn.cursor() as cur:
            cur.execute(_BOOTSTRAP_SQL)
            conn.commit()

            cur.execute('SELECT filename FROM schema_migrations')
            applied = {row[0] for row in cur.fetchall()}

        for path in files:
            name = path.name
            if name in applied:
                summary['skipped'].append(name)
                continue
            sql = path.read_text(encoding='utf-8')
            digest = _sha256_of(path)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        'INSERT INTO schema_migrations (filename, sha256) '
                        'VALUES (%s, %s)',
                        (name, digest),
                    )
                conn.commit()
                summary['applied'].append(name)
                logger.info('[migrations] applied %s', name)
            except Exception as exc:
                conn.rollback()
                summary['errors'].append({
                    'filename': name, 'error': f'{type(exc).__name__}: {exc}',
                })
                logger.error('[migrations] FAILED %s: %s', name, exc)
    finally:
        conn.close()

    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    s = apply_migrations()
    print(f"applied: {s['applied']}")
    print(f"skipped: {s['skipped']}")
    print(f"errors:  {s['errors']}")
    return 0 if not s['errors'] else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
