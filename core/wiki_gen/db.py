"""
Database schema and helpers for wiki generation.

Table:
    cairn_wiki_generation_log — per-article generation audit trail
"""
import os
import psycopg2
from contextlib import contextmanager


def get_db_url() -> str:
    return os.getenv('DATABASE_URL', 'postgresql://postgres:postgres123@localhost:5432/deek')


@contextmanager
def get_conn():
    conn = psycopg2.connect(get_db_url(), connect_timeout=5)
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema():
    """Create wiki generation tables if they don't exist. Called at Deek startup."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_SCHEMA)
            conn.commit()


_SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS cairn_wiki_generation_log (
    id               SERIAL PRIMARY KEY,
    source_type      VARCHAR(50),    -- 'direct_note' / 'cluster'
    topic            TEXT,           -- seed topic (cluster) or subject (direct note)
    source_email_ids INTEGER[],      -- contributing email IDs
    article_title    TEXT,
    wiki_filename    VARCHAR(500),   -- relative path under wiki/modules/
    quality_passed   BOOLEAN,
    quality_reason   TEXT,           -- 'local_pass' / 'claude_pass' / failure reason
    chunk_count      INTEGER,        -- email chunks that contributed
    tokens_used      INTEGER,        -- total API tokens (generation + quality check)
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS cairn_wiki_gen_log_source_idx
    ON cairn_wiki_generation_log(source_type);

CREATE INDEX IF NOT EXISTS cairn_wiki_gen_log_created_idx
    ON cairn_wiki_generation_log(created_at DESC);
"""
