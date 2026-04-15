"""SQLite-backed append log for cairn_delegate calls.

One row per call, success or failure. Separate from the prompt-level
``cost_log`` (different grain — see handover §1 issue 4). Stored in
the claw project's SQLite DB (``CLAW_DATA_DIR/claw.db`` by default) so
it sits alongside the rest of Cairn's per-project state.

``outcome`` is one of: success, schema_failure, api_error, refusal, timeout.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

Outcome = Literal["success", "schema_failure", "api_error", "refusal", "timeout"]

VALID_OUTCOMES: set[str] = {
    "success",
    "schema_failure",
    "api_error",
    "refusal",
    "timeout",
}


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cairn_delegation_log (
    id                  TEXT PRIMARY KEY,
    called_at           TEXT NOT NULL,
    delegating_session  TEXT NOT NULL,
    rationale           TEXT,
    task_type           TEXT NOT NULL,
    model_used          TEXT NOT NULL,
    tokens_in           INTEGER NOT NULL DEFAULT 0,
    tokens_out          INTEGER NOT NULL DEFAULT 0,
    cost_gbp            REAL NOT NULL DEFAULT 0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    schema_valid        INTEGER,
    outcome             TEXT NOT NULL CHECK (outcome IN (
        'success','schema_failure','api_error','refusal','timeout'
    )),
    output_excerpt      TEXT
)
"""

CREATE_INDEX_CALLED_AT = (
    "CREATE INDEX IF NOT EXISTS idx_cairn_delegation_log_called_at "
    "ON cairn_delegation_log(called_at)"
)
CREATE_INDEX_SESSION = (
    "CREATE INDEX IF NOT EXISTS idx_cairn_delegation_log_session "
    "ON cairn_delegation_log(delegating_session)"
)


def _default_db_path() -> Path:
    data_dir = os.getenv("CLAW_DATA_DIR", "./data")
    return Path(data_dir) / "claw.db"


def ensure_table(db_path: Path | None = None) -> Path:
    """Create the log table + indexes if absent. Returns the db path used."""
    path = db_path or _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_CALLED_AT)
        conn.execute(CREATE_INDEX_SESSION)
        conn.commit()
    return path


def insert_log(
    *,
    delegating_session: str,
    rationale: str,
    task_type: str,
    model_used: str,
    tokens_in: int,
    tokens_out: int,
    cost_gbp: float,
    duration_ms: int,
    schema_valid: bool | None,
    outcome: str,
    output_excerpt: str,
    db_path: Path | None = None,
) -> str:
    """Insert one row. Returns the generated id. Never raises for the caller —
    the ``cairn_delegate`` endpoint wraps this in its own try/except so that
    log-write failure cannot bring down the delegating session."""
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(VALID_OUTCOMES)}; got {outcome!r}")

    row_id = str(uuid.uuid4())
    called_at = datetime.now(timezone.utc).isoformat()
    path = db_path or _default_db_path()
    ensure_table(path)
    # Truncate excerpt at 500 chars to match the table contract.
    excerpt = (output_excerpt or "")[:500]

    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            INSERT INTO cairn_delegation_log (
                id, called_at, delegating_session, rationale,
                task_type, model_used, tokens_in, tokens_out,
                cost_gbp, duration_ms, schema_valid, outcome, output_excerpt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                called_at,
                delegating_session,
                rationale,
                task_type,
                model_used,
                int(tokens_in),
                int(tokens_out),
                float(cost_gbp),
                int(duration_ms),
                None if schema_valid is None else int(bool(schema_valid)),
                outcome,
                excerpt,
            ),
        )
        conn.commit()
    return row_id
