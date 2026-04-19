"""Nightly memory consolidation — Brief 2 Phase B.

Samples high-salience recent memories, clusters by pairwise cosine,
and asks the local Ollama model to extract a recurring pattern /
decision principle per cluster. Survivors (confidence >= 0.7, >= 3
source memories, not duplicates of existing active schemas) are
written to the `schemas` table in Postgres.

Runs nightly via Hetzner cron at 02:00 UTC. See scripts/consolidate_memories.py
and docs/IMPRESSIONS.md.

Design notes:
- Cost budget: zero cloud calls. All inference goes through
  OLLAMA_BASE_URL which resolves to deek-gpu via Tailscale.
- Idempotent: re-runs against the same window produce the same
  clusters and either reproduce existing schemas (deduped by cosine
  > 0.9) or refuse to write again.
- Failure isolation: clustering / LLM / embedding failures are logged
  and swallowed per-cluster. One bad cluster doesn't abort the run.
- Hard cap: 500 active schemas. When the table exceeds that, the
  oldest `dormant` (or the lowest-salience `active`) are demoted
  to free room.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


# ── Tuning ────────────────────────────────────────────────────────────

WINDOW_DAYS_DEFAULT = 30
CANDIDATE_LIMIT_DEFAULT = 50
MAX_SCHEMAS_DEFAULT = 10
MIN_CLUSTER_SIZE = 3
MIN_CONFIDENCE = 0.7
DEDUPE_COSINE_THRESHOLD = 0.9
ACTIVE_SCHEMA_HARD_CAP = 500

# Clustering uses a simple agglomerative threshold. Memories with
# pairwise cosine >= this are merged into the same cluster.
CLUSTER_SIMILARITY_THRESHOLD = 0.55

MEMORY_CHUNK_TYPES = ('memory', 'email', 'wiki', 'module_snapshot', 'social_post')


# ── Data types ────────────────────────────────────────────────────────

@dataclass
class CandidateMemory:
    chunk_id: int
    project_id: str
    file_path: str
    chunk_content: str
    salience: float
    last_accessed_at: datetime
    embedding: list[float]


@dataclass
class SchemaCandidate:
    statement: str
    source_memory_ids: list[int]
    confidence: float


@dataclass
class ConsolidationRun:
    started_at: datetime
    window_days: int
    candidates_considered: int
    clusters_formed: int
    llm_calls: int
    schemas_written: int
    schemas_skipped_dedup: int
    schemas_skipped_confidence: int
    schemas_skipped_grounding: int
    schemas_skipped_empty: int
    runtime_seconds: float
    errors: list[str]


# ── Helpers ───────────────────────────────────────────────────────────

def _db_url() -> str:
    u = os.getenv('DATABASE_URL', '')
    if not u:
        raise RuntimeError('DATABASE_URL not set')
    return u


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))


def _hours_since(ts: datetime) -> float:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0)


# ── Candidate sampling ────────────────────────────────────────────────

def sample_candidates(
    window_days: int,
    limit: int,
    tau_hours: float = 72.0,
) -> list[CandidateMemory]:
    """Pull top-N memories from the last N days ranked by salience x recency.

    Ranking is done in SQL using exp(-hours_since_access / tau) so we
    can pull a bounded slice without loading the entire memory history.
    """
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(_db_url(), connect_timeout=5)
    try:
        types_sql = ','.join(['%s'] * len(MEMORY_CHUNK_TYPES))
        with conn.cursor() as cur:
            # pgvector embeddings come back as numpy arrays; register_vector
            # casts them to list[float] cleanly.
            try:
                from pgvector.psycopg2 import register_vector
                register_vector(conn)
            except Exception:
                pass
            cur.execute(
                f"""
                SELECT id, project_id, file_path, chunk_content, salience,
                       last_accessed_at, embedding
                  FROM claw_code_chunks
                 WHERE chunk_type IN ({types_sql})
                   AND embedding IS NOT NULL
                   AND indexed_at >= NOW() - INTERVAL '%s days'
                 ORDER BY salience
                       * EXP(-EXTRACT(EPOCH FROM NOW() - last_accessed_at)
                             / (3600 * %s)) DESC
                 LIMIT %s
                """,
                (*MEMORY_CHUNK_TYPES, window_days, tau_hours, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    out: list[CandidateMemory] = []
    for row in rows:
        emb = row[6]
        if emb is None:
            continue
        try:
            emb_list = [float(x) for x in list(emb)]
        except Exception:
            continue
        out.append(CandidateMemory(
            chunk_id=int(row[0]),
            project_id=str(row[1]),
            file_path=str(row[2]),
            chunk_content=str(row[3]),
            salience=float(row[4] or 1.0),
            last_accessed_at=row[5],
            embedding=emb_list,
        ))
    return out


# ── Clustering ────────────────────────────────────────────────────────

def cluster_candidates(
    candidates: list[CandidateMemory],
    threshold: float = CLUSTER_SIMILARITY_THRESHOLD,
) -> list[list[CandidateMemory]]:
    """Simple single-link agglomerative clustering by pairwise cosine.

    For N <= 50 candidates the O(N^2) cost is trivial. Returns clusters
    with >= MIN_CLUSTER_SIZE members; singletons and pairs are dropped.
    """
    n = len(candidates)
    if n == 0:
        return []
    # Union-Find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _cosine(candidates[i].embedding, candidates[j].embedding) >= threshold:
                union(i, j)

    groups: dict[int, list[CandidateMemory]] = {}
    for i, c in enumerate(candidates):
        groups.setdefault(find(i), []).append(c)

    return [g for g in groups.values() if len(g) >= MIN_CLUSTER_SIZE]


# ── Ollama call ───────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """Here are {n} memories from recent work at NBNE. Read them together and decide whether a single recurring pattern, rule, or decision principle emerges that would be useful to remember.

Rules:
- If nothing meaningful stands out, respond with the single word NONE.
- Otherwise respond with ONLY a JSON object, no prose before or after:
  {{"statement": "one-sentence pattern in plain English", "source_memory_ids": [integer ids from the list below], "confidence": 0.0-1.0}}
- source_memory_ids MUST be drawn from the ids listed below. Include at least 3.
- Keep the statement concrete and actionable. Avoid platitudes.

Memories:
{memory_block}

JSON response or NONE:"""


def call_ollama_consolidation(
    cluster: list[CandidateMemory],
    ollama_base: str,
    model: str,
    timeout: float = 60.0,
) -> SchemaCandidate | None:
    """Ask the local model to extract a pattern from one cluster.

    Returns None on any failure: malformed JSON, NONE response, missing
    required fields, source ids not in the input set, etc.
    """
    import httpx
    memory_block = '\n\n'.join(
        f'[id {m.chunk_id}] {m.chunk_content[:1200]}'
        for m in cluster
    )
    prompt = _PROMPT_TEMPLATE.format(n=len(cluster), memory_block=memory_block)

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(
                f'{ollama_base.rstrip("/")}/api/chat',
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'stream': False,
                    'options': {'num_predict': 400, 'temperature': 0.2},
                },
            )
        if r.status_code != 200:
            logger.warning('[consolidation] ollama %s: %s', r.status_code, r.text[:200])
            return None
        content = (r.json().get('message') or {}).get('content', '').strip()
    except Exception as exc:
        logger.warning('[consolidation] ollama call failed: %s', exc)
        return None

    if not content or content.upper().startswith('NONE'):
        return None

    # Parse JSON — tolerate surrounding prose by finding the first {..}
    start = content.find('{')
    end = content.rfind('}')
    if start < 0 or end < start:
        logger.debug('[consolidation] no JSON in response: %s', content[:200])
        return None
    try:
        data = json.loads(content[start:end + 1])
    except Exception as exc:
        logger.debug('[consolidation] JSON parse failed: %s (%s)', exc, content[:200])
        return None

    statement = str(data.get('statement') or '').strip()
    ids_raw = data.get('source_memory_ids') or []
    try:
        ids = [int(i) for i in ids_raw]
    except Exception:
        return None
    try:
        conf = float(data.get('confidence', 0.0))
    except Exception:
        conf = 0.0

    if not statement or not ids:
        return None

    # Ids must be from the input cluster — drop any that aren't.
    cluster_ids = {m.chunk_id for m in cluster}
    grounded = [i for i in ids if i in cluster_ids]
    if len(grounded) < MIN_CLUSTER_SIZE:
        return None

    return SchemaCandidate(
        statement=statement, source_memory_ids=grounded, confidence=conf,
    )


# ── Schema write + dedupe ─────────────────────────────────────────────

def _embed_statement(statement: str) -> list[float] | None:
    """Embed the schema statement using the same model used for memory."""
    try:
        from core.wiki.embeddings import get_embed_fn
        fn = get_embed_fn()
        if fn is None:
            return None
        v = fn(statement[:6000])
        return [float(x) for x in v] if v else None
    except Exception as exc:
        logger.debug('[consolidation] embed failed: %s', exc)
        return None


def _active_schema_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM schemas WHERE status = 'active'")
        (n,) = cur.fetchone()
    return int(n)


def _is_duplicate(conn, embedding: list[float]) -> bool:
    """True if an active schema already exists within DEDUPE_COSINE_THRESHOLD."""
    if not embedding:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """SELECT MAX(1 - (embedding <=> %s::vector))
                 FROM schemas
                WHERE status = 'active' AND embedding IS NOT NULL""",
            (embedding,),
        )
        (sim,) = cur.fetchone()
    return sim is not None and float(sim) >= DEDUPE_COSINE_THRESHOLD


def _demote_to_make_room(conn) -> None:
    """Enforce the hard cap: demote lowest-salience active schemas."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM schemas WHERE status = 'active'")
        (n,) = cur.fetchone()
        overflow = int(n) - ACTIVE_SCHEMA_HARD_CAP
        if overflow > 0:
            cur.execute(
                """UPDATE schemas SET status = 'dormant'
                    WHERE id IN (
                      SELECT id FROM schemas
                       WHERE status = 'active'
                       ORDER BY salience ASC, last_accessed_at ASC
                       LIMIT %s)""",
                (overflow,),
            )


def write_schema(
    conn,
    candidate: SchemaCandidate,
    embedding: list[float],
    model: str,
) -> bool:
    """Insert one schema row. Returns True on success, False on any error."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO schemas
                    (id, schema_text, embedding, salience,
                     source_memory_ids, derived_at, last_accessed_at,
                     access_count, status, model, confidence)
                   VALUES (%s, %s, %s::vector, %s, %s::int[],
                           NOW(), NOW(), 0, 'active', %s, %s)""",
                (
                    str(uuid.uuid4()),
                    candidate.statement,
                    embedding,
                    1.0 + candidate.confidence * 2.0,  # seed salience 1..3
                    candidate.source_memory_ids,
                    model,
                    float(candidate.confidence),
                ),
            )
        return True
    except Exception as exc:
        logger.warning('[consolidation] write_schema failed: %s', exc)
        return False


# ── Last-run metadata ─────────────────────────────────────────────────

_RUN_LOG_PATH = os.getenv(
    'DEEK_CONSOLIDATION_LOG',
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', '..', 'data', 'consolidation_runs.jsonl',
    ),
)


def _record_run(run: ConsolidationRun) -> None:
    try:
        path = os.path.abspath(_RUN_LOG_PATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {
            'started_at': run.started_at.isoformat(),
            'window_days': run.window_days,
            'candidates_considered': run.candidates_considered,
            'clusters_formed': run.clusters_formed,
            'llm_calls': run.llm_calls,
            'schemas_written': run.schemas_written,
            'schemas_skipped_dedup': run.schemas_skipped_dedup,
            'schemas_skipped_confidence': run.schemas_skipped_confidence,
            'schemas_skipped_grounding': run.schemas_skipped_grounding,
            'schemas_skipped_empty': run.schemas_skipped_empty,
            'runtime_seconds': round(run.runtime_seconds, 2),
            'errors': run.errors[:10],
        }
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
    except Exception as exc:
        logger.debug('[consolidation] run log write failed: %s', exc)


def read_last_run() -> dict | None:
    """Return the most recent ConsolidationRun dict, or None."""
    try:
        path = os.path.abspath(_RUN_LOG_PATH)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            last = None
            for line in f:
                line = line.strip()
                if line:
                    last = line
            return json.loads(last) if last else None
    except Exception as exc:
        logger.debug('[consolidation] read_last_run failed: %s', exc)
        return None


# ── Entry point ───────────────────────────────────────────────────────

def consolidate_recent_memories(
    window_days: int = WINDOW_DAYS_DEFAULT,
    candidate_limit: int = CANDIDATE_LIMIT_DEFAULT,
    max_schemas: int = MAX_SCHEMAS_DEFAULT,
    ollama_base: str | None = None,
    model: str | None = None,
) -> ConsolidationRun:
    """Run one consolidation pass. Idempotent and failure-isolated.

    Args:
        window_days: only sample memories newer than this
        candidate_limit: top-N candidates pulled from the window
        max_schemas: stop after writing this many schemas
        ollama_base: override for OLLAMA_BASE_URL
        model: override for the Ollama model name

    Returns a ConsolidationRun describing what happened. A run with no
    candidates / no clusters / no survivors is NOT a failure.
    """
    import psycopg2
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    errors: list[str] = []

    ollama_base = ollama_base or os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    model = model or os.getenv(
        'OLLAMA_VOICE_MODEL',
        os.getenv('OLLAMA_CLASSIFIER_MODEL', 'qwen2.5:7b-instruct'),
    )

    candidates: list[CandidateMemory] = []
    clusters: list[list[CandidateMemory]] = []
    llm_calls = 0
    schemas_written = 0
    skipped_dedup = 0
    skipped_conf = 0
    skipped_ground = 0
    skipped_empty = 0

    try:
        candidates = sample_candidates(window_days, candidate_limit)
        logger.info('[consolidation] candidates=%d window=%dd',
                    len(candidates), window_days)
    except Exception as exc:
        errors.append(f'sample_candidates: {type(exc).__name__}: {exc}')
        logger.error('[consolidation] sample_candidates failed: %s', exc)

    if candidates:
        try:
            clusters = cluster_candidates(candidates)
            logger.info('[consolidation] clusters=%d', len(clusters))
        except Exception as exc:
            errors.append(f'cluster_candidates: {type(exc).__name__}: {exc}')
            logger.error('[consolidation] clustering failed: %s', exc)

    if clusters:
        try:
            conn = psycopg2.connect(_db_url(), connect_timeout=5)
        except Exception as exc:
            errors.append(f'db_connect: {type(exc).__name__}: {exc}')
            conn = None
        else:
            try:
                _demote_to_make_room(conn)
                conn.commit()

                for cluster in clusters:
                    if schemas_written >= max_schemas:
                        break
                    try:
                        llm_calls += 1
                        cand = call_ollama_consolidation(cluster, ollama_base, model)
                    except Exception as exc:
                        errors.append(f'ollama: {exc}')
                        continue
                    if cand is None:
                        skipped_empty += 1
                        continue
                    if cand.confidence < MIN_CONFIDENCE:
                        skipped_conf += 1
                        continue
                    if len(cand.source_memory_ids) < MIN_CLUSTER_SIZE:
                        skipped_ground += 1
                        continue
                    embedding = _embed_statement(cand.statement)
                    if embedding is None:
                        skipped_empty += 1
                        continue
                    if _is_duplicate(conn, embedding):
                        skipped_dedup += 1
                        continue
                    if write_schema(conn, cand, embedding, model):
                        conn.commit()
                        schemas_written += 1
                    else:
                        conn.rollback()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    runtime = time.monotonic() - t0
    run = ConsolidationRun(
        started_at=started,
        window_days=window_days,
        candidates_considered=len(candidates),
        clusters_formed=len(clusters),
        llm_calls=llm_calls,
        schemas_written=schemas_written,
        schemas_skipped_dedup=skipped_dedup,
        schemas_skipped_confidence=skipped_conf,
        schemas_skipped_grounding=skipped_ground,
        schemas_skipped_empty=skipped_empty,
        runtime_seconds=runtime,
        errors=errors,
    )
    _record_run(run)
    return run


__all__ = [
    'CandidateMemory', 'SchemaCandidate', 'ConsolidationRun',
    'sample_candidates', 'cluster_candidates', 'call_ollama_consolidation',
    'write_schema', 'consolidate_recent_memories', 'read_last_run',
]
