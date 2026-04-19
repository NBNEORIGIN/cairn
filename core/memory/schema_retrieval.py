"""Schema retrieval — Brief 2 Phase B Task 7.

On retrieval, if the query looks strategic (architecture / decision /
planning / long-form), pull the top-K schemas by cosine similarity
against the query and return them alongside memory hits. Schemas carry
a 1.5x RRF boost because they're already distilled — each row carries
more per-token signal than a raw memory.

Exposed as `retrieve_schemas()` — called from the hybrid retriever's
`retrieve()` method. Returns a list of dicts with enough metadata for
Deek to cite the schema ('Based on a pattern noticed across...').
"""
from __future__ import annotations

import logging
import os
import re
from typing import Callable

logger = logging.getLogger(__name__)


# Keywords that suggest the query is strategic rather than an
# information lookup. The heuristic is deliberately loose — false
# positives are cheap (a few extra tokens), false negatives lose Deek
# the impression layer's output.
_STRATEGIC_KEYWORDS = (
    'architect', 'design', 'decision', 'decide', 'plan', 'strategy',
    'approach', 'trade-off', 'tradeoff', 'tradeoffs', 'principle',
    'pattern', 'recurring', 'lesson', 'why do we', 'why are we',
    'should we', 'what should', 'how should',
)

# Strategic queries also tend to be longer. Anything over this token
# count gets schema retrieval whether keywords hit or not.
_STRATEGIC_TOKEN_THRESHOLD = 20


def is_strategic_query(text: str) -> bool:
    """Heuristic: does this query deserve schema retrieval?"""
    if not text:
        return False
    lower = text.lower()
    if any(kw in lower for kw in _STRATEGIC_KEYWORDS):
        return True
    # Rough token count — cheaper than tiktoken for the common case.
    tokens = re.findall(r'\S+', text)
    return len(tokens) >= _STRATEGIC_TOKEN_THRESHOLD


def retrieve_schemas(
    query: str,
    embedding_fn: Callable[[str], list[float]] | None,
    top_k: int = 3,
    min_similarity: float = 0.3,
) -> list[dict]:
    """Return top-K active schemas most similar to the query.

    Each result dict has:
        id              UUID string
        statement       schema_text
        similarity      cosine similarity 0..1
        salience        current salience 0..10
        confidence      filter confidence at creation
        source_memory_ids list of chunk_ids
        derived_at      ISO string
        boosted_score   similarity * 1.5 for RRF merging

    Returns [] on any error — schemas are a bonus, not a dependency.
    """
    if not query or embedding_fn is None:
        return []
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return []

    try:
        q_vec = embedding_fn(query)
    except Exception as exc:
        logger.debug('[schema_retrieval] embed failed: %s', exc)
        return []
    if not q_vec:
        return []

    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=5)
    except Exception as exc:
        logger.debug('[schema_retrieval] db connect failed: %s', exc)
        return []

    try:
        with conn.cursor() as cur:
            # Brief 4 Phase C: dormant schemas are retrievable but at
            # a lower weight — they're still findable but rank below
            # active ones with similar similarity.
            cur.execute(
                """
                SELECT id::text, schema_text, salience, confidence,
                       source_memory_ids, derived_at, status,
                       1 - (embedding <=> %s::vector) AS similarity
                  FROM schemas
                 WHERE status IN ('active', 'dormant')
                   AND embedding IS NOT NULL
                 ORDER BY embedding <=> %s::vector
                 LIMIT %s
                """,
                (q_vec, q_vec, top_k),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.debug('[schema_retrieval] query failed: %s', exc)
        try:
            conn.close()
        except Exception:
            pass
        return []

    try:
        conn.close()
    except Exception:
        pass

    results: list[dict] = []
    for row in rows:
        status = str(row[6] or 'active')
        sim = float(row[7] or 0.0)
        if sim < min_similarity:
            continue
        # Active schemas: 1.5x boost. Dormant: 0.75x (retrievable but
        # half the weight of active — Task 10 of Brief 4 Phase C).
        boost_factor = 1.5 if status == 'active' else 0.75
        results.append({
            'id': row[0],
            'statement': row[1],
            'salience': float(row[2] or 1.0),
            'confidence': float(row[3] or 0.0),
            'source_memory_ids': list(row[4] or []),
            'derived_at': row[5].isoformat() if row[5] else None,
            'status': status,
            'similarity': sim,
            'boosted_score': sim * boost_factor,
        })
    return results


def reinforce_schemas_async(schema_ids: list[str]) -> None:
    """Fire-and-forget bump on retrieved schemas — mirrors memory path."""
    import threading
    if not schema_ids:
        return
    t = threading.Thread(
        target=_reinforce_schemas_sync, args=(schema_ids,),
        name='deek-schema-reinforce', daemon=True,
    )
    t.start()


def _reinforce_schemas_sync(schema_ids: list[str]) -> None:
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url or not schema_ids:
        return
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=5)
        try:
            with conn.cursor() as cur:
                # Brief 4 Phase C: dormant schemas that get retrieved
                # are re-activated. Reinforcement still applies; the
                # status flip is what takes it out of the "stale"
                # bucket so the next decay sweep leaves it alone.
                cur.execute(
                    """UPDATE schemas
                          SET access_count = access_count + 1,
                              last_accessed_at = NOW(),
                              salience = LEAST(10.0, salience + 0.1),
                              status = CASE
                                WHEN status = 'dormant' THEN 'active'
                                ELSE status
                              END
                        WHERE id::text = ANY(%s::text[])
                          AND status IN ('active', 'dormant')""",
                    (schema_ids,),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug('[schema_retrieval] reinforcement failed: %s', exc)


__all__ = ['is_strategic_query', 'retrieve_schemas', 'reinforce_schemas_async']
