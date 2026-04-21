"""
Database schema and connection helpers for the Deek counterfactual
intelligence module (``cairn_intel`` schema).

All tables live in a dedicated Postgres schema so they never collide
with ``claw_code_chunks``, ``cairn_email_raw`` or any other module.

Tables:
    cairn_intel.decisions         — one row per historical or live decision
    cairn_intel.decision_outcomes — what actually happened after the decision
    cairn_intel.module_dissents   — who argued for which rejected_path
    cairn_intel.backfill_runs     — ledger of importer invocations
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2


def get_db_url() -> str:
    return os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres123@localhost:5432/deek',
    )


@contextmanager
def get_conn(db_url: str | None = None):
    """Open a psycopg2 connection with pgvector registered when available."""
    conn = psycopg2.connect(db_url or get_db_url(), connect_timeout=5)
    try:
        try:
            from pgvector.psycopg2 import register_vector
            register_vector(conn)
        except Exception:
            # Not fatal — the schema uses vector columns but raw SQL casts
            # still work without the adapter registered.
            pass
        yield conn
    finally:
        conn.close()


_SQL_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS cairn_intel;

-- One row per historical or live decision.
CREATE TABLE IF NOT EXISTS cairn_intel.decisions (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    decided_at          TIMESTAMPTZ NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    backfill_run_id     TEXT,
    context_summary     TEXT NOT NULL,
    archetype_tags      TEXT[] NOT NULL DEFAULT '{}',
    chosen_path         TEXT NOT NULL,
    rejected_paths      JSONB,
    signal_strength     REAL NOT NULL,
    case_id             TEXT,
    embedding           vector(768),
    raw_source_ref      JSONB,
    committed           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_decisions_source
    ON cairn_intel.decisions(source);
CREATE INDEX IF NOT EXISTS idx_decisions_source_type
    ON cairn_intel.decisions(source_type);
CREATE INDEX IF NOT EXISTS idx_decisions_decided_at
    ON cairn_intel.decisions(decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_case_id
    ON cairn_intel.decisions(case_id) WHERE case_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_decisions_backfill_run
    ON cairn_intel.decisions(backfill_run_id)
    WHERE backfill_run_id IS NOT NULL;

-- Outcomes — what actually happened after a decision.
CREATE TABLE IF NOT EXISTS cairn_intel.decision_outcomes (
    id                  BIGSERIAL PRIMARY KEY,
    decision_id         TEXT NOT NULL
        REFERENCES cairn_intel.decisions(id) ON DELETE CASCADE,
    observed_at         TIMESTAMPTZ NOT NULL,
    actual_result       TEXT NOT NULL,
    chosen_path_score   REAL,
    metrics             JSONB,
    lesson              TEXT,
    lesson_model        TEXT,
    lesson_generated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outcomes_decision
    ON cairn_intel.decision_outcomes(decision_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_lesson
    ON cairn_intel.decision_outcomes(decision_id)
    WHERE lesson IS NOT NULL;

-- Which module/voice argued for which alternative path.
CREATE TABLE IF NOT EXISTS cairn_intel.module_dissents (
    id                  BIGSERIAL PRIMARY KEY,
    decision_id         TEXT NOT NULL
        REFERENCES cairn_intel.decisions(id) ON DELETE CASCADE,
    module              TEXT NOT NULL,
    argued_for          TEXT NOT NULL,
    argument            TEXT,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dissents_decision
    ON cairn_intel.module_dissents(decision_id);
CREATE INDEX IF NOT EXISTS idx_dissents_module
    ON cairn_intel.module_dissents(module);

-- Backfill run ledger — one row per importer invocation.
CREATE TABLE IF NOT EXISTS cairn_intel.backfill_runs (
    id                  TEXT PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    sources_requested   TEXT[],
    mode                TEXT NOT NULL,
    counts_per_source   JSONB,
    claude_calls_used   INTEGER DEFAULT 0,
    bulk_llm_calls_used INTEGER DEFAULT 0,
    errors              JSONB,
    status              TEXT NOT NULL
);

-- Email triage ledger — one row per email the triage pipeline has
-- seen. Unique by email_message_id for idempotency; on re-run the
-- triage pipeline skips rows that already exist.
CREATE TABLE IF NOT EXISTS cairn_intel.email_triage (
    id                    BIGSERIAL PRIMARY KEY,
    email_message_id      TEXT UNIQUE NOT NULL,
    email_mailbox         TEXT NOT NULL,
    email_sender          TEXT,
    email_subject         TEXT,
    email_received_at     TIMESTAMPTZ,
    classification        TEXT NOT NULL,  -- new_enquiry | existing_project_reply | automation | personal | unclassified | error
    classification_confidence TEXT,        -- high | medium | low
    classification_reason TEXT,
    client_name_guess     TEXT,
    project_id            TEXT,            -- matched CRM project if any
    project_match_score   REAL,
    analyzer_brief        TEXT,            -- full analyzer output if classification == new_enquiry
    analyzer_job_size     TEXT,            -- small | mid | large, from analyzer provenance
    processed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_to_toby_at       TIMESTAMPTZ,    -- when the digest email went out; NULL if not yet sent
    send_dry_run          BOOLEAN DEFAULT FALSE,  -- true if SMTP was unavailable and the "send" was logged only
    send_error            TEXT,            -- most recent send error, if any
    send_attempts         INTEGER NOT NULL DEFAULT 0,  -- retry counter — capped at MAX_SEND_ATTEMPTS
    last_send_attempt_at  TIMESTAMPTZ,    -- when we last tried to send (for backoff + give-up cap)
    crm_recommendation_id TEXT,            -- ID from CRM /api/cairn/memory response
    skip_reason           TEXT
);

-- Defensive migration for existing deployments that predate the
-- retry columns. ALTER TABLE IF NOT EXISTS on columns was added in
-- PG 9.6, so this runs on every startup but is a no-op after the
-- first run.
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS send_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS last_send_attempt_at TIMESTAMPTZ;

-- Triage Phase A (2026-04-21): top-N match candidates + draft reply.
-- match_candidates carries the full top-N from the CRM search so the
-- digest can surface alternatives, not just the winner. draft_reply
-- is the Ollama-drafted response for the user to accept/edit.
-- reviewed_at + review_action track the user's reply-back feedback
-- (Phase B parses the reply and populates these).
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS match_candidates JSONB;
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS draft_reply TEXT;
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS draft_model TEXT;
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS review_action TEXT;
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS review_notes TEXT;
ALTER TABLE cairn_intel.email_triage
    ADD COLUMN IF NOT EXISTS project_folder_path TEXT;

CREATE INDEX IF NOT EXISTS idx_email_triage_unsent
    ON cairn_intel.email_triage(processed_at DESC)
    WHERE sent_to_toby_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_email_triage_classification
    ON cairn_intel.email_triage(classification);
CREATE INDEX IF NOT EXISTS idx_email_triage_received
    ON cairn_intel.email_triage(email_received_at DESC);
"""


_SQL_IVFFLAT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_decisions_embedding
    ON cairn_intel.decisions
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""


def ensure_schema(db_url: str | None = None, schema: str = 'cairn_intel') -> None:
    """Create the ``cairn_intel`` schema and tables if they don't exist.

    Safe to call at startup on every boot — idempotent. The ivfflat index
    is created only once the decisions table has a reasonable number of
    rows, matching the pattern in ``core/context/indexer.py``.

    The ``schema`` parameter exists so tests can target an alternate
    schema (e.g. ``cairn_intel_test``) without touching production data.
    """
    sql = _SQL_SCHEMA
    if schema != 'cairn_intel':
        sql = sql.replace('cairn_intel', schema)

    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()

            # IVFFlat index — only useful once there are rows.
            cur.execute(
                f"SELECT COUNT(*) FROM {schema}.decisions;"
            )
            row_count = cur.fetchone()[0]
            if row_count >= 100:
                idx_sql = _SQL_IVFFLAT_INDEX
                if schema != 'cairn_intel':
                    idx_sql = idx_sql.replace('cairn_intel', schema)
                cur.execute(idx_sql)
                conn.commit()


# ── Email triage helpers ────────────────────────────────────────────────


def upsert_email_triage(
    row: dict,
    db_url: str | None = None,
    schema: str = 'cairn_intel',
) -> int:
    """Insert or update a row in ``cairn_intel.email_triage``.

    Upsert key is ``email_message_id``. Returns the row id. Used by
    ``scripts.email_triage.triage_runner`` to record every classification
    attempt exactly once per email.
    """
    # Phase A: accept match_candidates + draft_reply + draft_model
    # as optional fields. Older callers that don't set them pass
    # None through cleanly.
    import json as _json
    row = dict(row)
    cands = row.get('match_candidates')
    row['match_candidates_json'] = (
        _json.dumps(cands) if cands is not None else None
    )
    row.setdefault('draft_reply', None)
    row.setdefault('draft_model', None)

    sql = f"""
    INSERT INTO {schema}.email_triage (
        email_message_id, email_mailbox, email_sender, email_subject,
        email_received_at, classification, classification_confidence,
        classification_reason, client_name_guess, project_id,
        project_match_score, analyzer_brief, analyzer_job_size,
        skip_reason, match_candidates, draft_reply, draft_model
    ) VALUES (
        %(email_message_id)s, %(email_mailbox)s, %(email_sender)s,
        %(email_subject)s, %(email_received_at)s, %(classification)s,
        %(classification_confidence)s, %(classification_reason)s,
        %(client_name_guess)s, %(project_id)s, %(project_match_score)s,
        %(analyzer_brief)s, %(analyzer_job_size)s, %(skip_reason)s,
        %(match_candidates_json)s::jsonb, %(draft_reply)s, %(draft_model)s
    )
    ON CONFLICT (email_message_id) DO UPDATE SET
        classification            = EXCLUDED.classification,
        classification_confidence = EXCLUDED.classification_confidence,
        classification_reason     = EXCLUDED.classification_reason,
        client_name_guess         = EXCLUDED.client_name_guess,
        project_id                = EXCLUDED.project_id,
        project_match_score       = EXCLUDED.project_match_score,
        analyzer_brief            = EXCLUDED.analyzer_brief,
        analyzer_job_size         = EXCLUDED.analyzer_job_size,
        skip_reason               = EXCLUDED.skip_reason,
        match_candidates          = EXCLUDED.match_candidates,
        draft_reply               = EXCLUDED.draft_reply,
        draft_model               = EXCLUDED.draft_model,
        processed_at              = NOW()
    RETURNING id
    """
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, row)
            new_id = cur.fetchone()[0]
            conn.commit()
    return int(new_id)


# Give-up cap — after this many failed SMTP attempts on a single row
# we stop retrying. The cron fires every 5 min so 5 attempts ≈ 25 min
# of coverage for transient IONOS blips. Permanent failures (bad auth,
# invalid sender) get escalated to Toby via the send_error column.
MAX_SEND_ATTEMPTS = 5


def load_unsent_triage_drafts(
    db_url: str | None = None,
    limit: int = 100,
    schema: str = 'cairn_intel',
) -> list[dict]:
    """Return triage rows that have not yet been sent to Toby.

    Used by the digest sender cron. Only returns rows with a non-empty
    analyzer_brief OR rows classified as existing_project_reply (those
    also get a summary email). Rows with send_attempts >= MAX_SEND_ATTEMPTS
    are excluded so a permanent SMTP failure can't burn budget on
    infinite retries.
    """
    sql = f"""
    SELECT id, email_message_id, email_mailbox, email_sender,
           email_subject, email_received_at, classification,
           classification_confidence, client_name_guess, project_id,
           analyzer_brief, analyzer_job_size, processed_at,
           send_attempts, send_error,
           match_candidates, draft_reply, draft_model,
           project_match_score
    FROM {schema}.email_triage
    WHERE sent_to_toby_at IS NULL
      AND classification IN ('new_enquiry', 'existing_project_reply')
      AND send_attempts < %s
    ORDER BY email_received_at DESC NULLS LAST
    LIMIT %s
    """
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (MAX_SEND_ATTEMPTS, limit))
            col_names = [d[0] for d in cur.description]
            return [dict(zip(col_names, row)) for row in cur.fetchall()]


def mark_triage_sent(
    triage_id: int,
    dry_run: bool = False,
    send_error: str | None = None,
    crm_recommendation_id: str | None = None,
    db_url: str | None = None,
    schema: str = 'cairn_intel',
) -> None:
    """Mark a triage row as delivered to Toby (or dry-run logged).

    Behaviour:
        - Success (no error):   sent_to_toby_at = NOW(), increments send_attempts
        - Dry-run (no SMTP):    sent_to_toby_at = NOW(), send_dry_run = TRUE
        - Error (SMTP fail):    sent_to_toby_at stays NULL, send_error populated,
                                 send_attempts incremented. Row re-enters the
                                 queue next cron cycle until MAX_SEND_ATTEMPTS
                                 is hit (then load_unsent_triage_drafts skips it).
    """
    # On failure, leave sent_to_toby_at NULL so the row retries.
    # On success or dry-run, stamp it so it never re-delivers.
    should_stamp_sent = send_error is None
    sql = f"""
    UPDATE {schema}.email_triage
    SET sent_to_toby_at       = CASE WHEN %s THEN NOW() ELSE sent_to_toby_at END,
        send_dry_run          = %s,
        send_error            = %s,
        send_attempts         = send_attempts + 1,
        last_send_attempt_at  = NOW(),
        crm_recommendation_id = COALESCE(%s, crm_recommendation_id)
    WHERE id = %s
    """
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (should_stamp_sent, bool(dry_run), send_error,
                 crm_recommendation_id, triage_id),
            )
            conn.commit()


def already_triaged_message_ids(
    message_ids: list[str],
    db_url: str | None = None,
    schema: str = 'cairn_intel',
) -> set[str]:
    """Return the subset of message_ids already present in email_triage.

    Used by the runner to skip already-processed emails without hitting
    Haiku again.
    """
    if not message_ids:
        return set()
    sql = f"""
    SELECT email_message_id FROM {schema}.email_triage
    WHERE email_message_id = ANY(%s)
    """
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (message_ids,))
            return {row[0] for row in cur.fetchall()}


def drop_schema(db_url: str | None = None, schema: str = 'cairn_intel_test') -> None:
    """Drop a cairn_intel test schema. Never used against production."""
    if schema == 'cairn_intel':
        raise RuntimeError(
            'Refusing to drop the production cairn_intel schema'
        )
    with get_conn(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE;')
            conn.commit()
