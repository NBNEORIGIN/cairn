"""
Database schema and connection helpers for the Cairn counterfactual
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
        'postgresql://postgres:postgres123@localhost:5432/claw',
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
