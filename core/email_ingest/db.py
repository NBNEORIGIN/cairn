"""
Database schema and helpers for Deek email ingestion.

Tables:
    cairn_email_raw        — sanitised email store (raw text, not embedded)
    cairn_email_ingest_log — run-level checkpoint for bulk ingest resume
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
    """Create all email ingest tables if they don't exist. Called at Deek startup."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_SCHEMA)
            conn.commit()


_SQL_SCHEMA = """
-- Raw sanitised email store
CREATE TABLE IF NOT EXISTS cairn_email_raw (
    id              SERIAL PRIMARY KEY,
    message_id      VARCHAR(500) UNIQUE NOT NULL,
    mailbox         VARCHAR(100) NOT NULL,
    sender          TEXT,
    recipients      TEXT[],
    subject         TEXT,
    body_text       TEXT,
    body_html       TEXT,
    received_at     TIMESTAMPTZ,
    thread_id       VARCHAR(500),
    labels          TEXT[],
    is_embedded     BOOLEAN DEFAULT FALSE,
    skip_reason     TEXT,
    word_count      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS cairn_email_raw_mailbox_idx
    ON cairn_email_raw(mailbox);

CREATE INDEX IF NOT EXISTS cairn_email_raw_received_idx
    ON cairn_email_raw(received_at DESC);

CREATE INDEX IF NOT EXISTS cairn_email_raw_embedded_idx
    ON cairn_email_raw(is_embedded)
    WHERE is_embedded = FALSE;

CREATE INDEX IF NOT EXISTS cairn_email_raw_thread_idx
    ON cairn_email_raw(thread_id)
    WHERE thread_id IS NOT NULL;

-- Run-level checkpoint for bulk ingest (enables resume after failure)
CREATE TABLE IF NOT EXISTS cairn_email_ingest_log (
    id              SERIAL PRIMARY KEY,
    mailbox         VARCHAR(100),
    run_started     TIMESTAMPTZ,
    run_ended       TIMESTAMPTZ,
    total_fetched   INTEGER,
    total_stored    INTEGER,
    total_skipped   INTEGER,
    total_errors    INTEGER,
    last_message_id VARCHAR(500),
    status          VARCHAR(20)
);

-- Learned filters — populated when Toby replies to a triage digest with
-- a SPAM / PERSONAL classification. Future emails matching this sender
-- (exact email or domain) skip the digest pipeline at filter-check time.
--
-- ``match_type``:
--   'exact'   — match the full sender email (e.g. `bob@example.com`)
--   'domain'  — match the @-suffix (e.g. `@spammy-marketers.com`)
--
-- ``classification``:
--   'spam'      — junk/marketing; filter skip reason = 'learned_spam'
--   'personal'  — personal contact that ended up in business inbox
--   'newsletter' — non-spam non-business automation; reserved for future use
--
-- ``learned_from_triage_id`` — audit trail; null for filters added via
-- admin tools rather than the reply-back loop.
CREATE TABLE IF NOT EXISTS cairn_email_learned_filters (
    id                     SERIAL PRIMARY KEY,
    sender                 TEXT NOT NULL,
    match_type             VARCHAR(20) NOT NULL,
    classification         VARCHAR(20) NOT NULL,
    learned_from_triage_id INTEGER,
    learned_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    learned_by             TEXT,
    CONSTRAINT cairn_email_learned_filters_unique
        UNIQUE (sender, match_type, classification)
);
CREATE INDEX IF NOT EXISTS cairn_email_learned_filters_sender_idx
    ON cairn_email_learned_filters (LOWER(sender));
"""
