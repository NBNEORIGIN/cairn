"""
CounterfactualMemory — the API surface for the cairn_intel module.

Used by:
    - The historical backfill importer (``scripts/backfill/*``)
      via ``record_historical_decision``.
    - Future live-decision recording via ``record_decision``.
    - The ``retrieve_similar_decisions`` chat tool via ``retrieve_similar``.

Embeddings are produced by ``core.wiki.embeddings.get_embed_fn`` — the
same cascading Ollama → OpenAI → DeepSeek provider the rest of Cairn
uses. The class accepts an injected ``embed_fn`` so tests can pass a
deterministic fake without patching providers.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterable

import psycopg2
from psycopg2.extras import Json


EmbedFn = Callable[[str], list[float] | None]


class CounterfactualMemory:
    """Wrapper over the ``cairn_intel`` schema.

    Thread-safety: each public method opens and closes its own
    connection, so the instance is safe to share across request
    handlers in the cairn-api process.
    """

    def __init__(
        self,
        db_url: str,
        embed_fn: EmbedFn,
        schema: str = 'cairn_intel',
    ):
        self.db_url = db_url
        self.embed_fn = embed_fn
        self.schema = schema

    # ── Connection helpers ──────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        conn = psycopg2.connect(self.db_url, connect_timeout=5)
        try:
            try:
                from pgvector.psycopg2 import register_vector
                register_vector(conn)
            except Exception:
                pass
            yield conn
        finally:
            conn.close()

    # ── Embedding ───────────────────────────────────────────────────────

    def _compute_embedding(
        self,
        context_summary: str,
        archetype_tags: list[str],
    ) -> list[float] | None:
        """Embed the joined tags + summary. Returns None if no provider."""
        text = ' '.join(archetype_tags) + ' ' + context_summary
        try:
            vec = self.embed_fn(text[:4000])
        except Exception:
            return None
        if not vec:
            return None
        return list(vec)

    # ── Record — live path ──────────────────────────────────────────────

    def record_decision(
        self,
        decision_id: str,
        source_type: str,
        context_summary: str,
        archetype_tags: list[str],
        chosen_path: str,
        rejected_paths: list[dict] | None = None,
        case_id: str | None = None,
        raw_source_ref: dict | None = None,
    ) -> None:
        """Record a decision made live by a running module.

        Live decisions are always committed=TRUE and source='live'.
        The live path is not exercised in the Phase 1 tests but the
        method exists so the backfill path is clearly separated from it.
        """
        self._upsert_decision(
            decision_id=decision_id,
            source='live',
            source_type=source_type,
            decided_at=datetime.utcnow(),
            context_summary=context_summary,
            archetype_tags=archetype_tags,
            chosen_path=chosen_path,
            rejected_paths=rejected_paths,
            signal_strength=1.0,
            case_id=case_id,
            raw_source_ref=raw_source_ref,
            backfill_run_id=None,
            committed=True,
        )

    # ── Record — backfill path ──────────────────────────────────────────

    def record_historical_decision(
        self,
        decision_id: str,
        source_type: str,
        decided_at: datetime,
        context_summary: str,
        archetype_tags: list[str],
        chosen_path: str,
        rejected_paths: list[dict] | None = None,
        signal_strength: float = 0.8,
        case_id: str | None = None,
        raw_source_ref: dict | None = None,
        backfill_run_id: str | None = None,
        committed: bool = True,
    ) -> None:
        """Idempotent upsert by decision_id.

        Embedding is computed here from the archetype tags + context
        summary. ``signal_strength`` is clamped to the range [0.0, 1.0].
        """
        clamped = max(0.0, min(1.0, float(signal_strength)))
        self._upsert_decision(
            decision_id=decision_id,
            source='backfill',
            source_type=source_type,
            decided_at=decided_at,
            context_summary=context_summary,
            archetype_tags=archetype_tags,
            chosen_path=chosen_path,
            rejected_paths=rejected_paths,
            signal_strength=clamped,
            case_id=case_id,
            raw_source_ref=raw_source_ref,
            backfill_run_id=backfill_run_id,
            committed=committed,
        )

    # ── Shared upsert implementation ────────────────────────────────────

    def _upsert_decision(
        self,
        decision_id: str,
        source: str,
        source_type: str,
        decided_at: datetime,
        context_summary: str,
        archetype_tags: list[str],
        chosen_path: str,
        rejected_paths: list[dict] | None,
        signal_strength: float,
        case_id: str | None,
        raw_source_ref: dict | None,
        backfill_run_id: str | None,
        committed: bool,
    ) -> None:
        embedding = self._compute_embedding(context_summary, archetype_tags)

        sql = f"""
        INSERT INTO {self.schema}.decisions (
            id, source, source_type, decided_at, backfill_run_id,
            context_summary, archetype_tags, chosen_path, rejected_paths,
            signal_strength, case_id, embedding, raw_source_ref, committed
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (id) DO UPDATE SET
            source          = EXCLUDED.source,
            source_type     = EXCLUDED.source_type,
            decided_at      = EXCLUDED.decided_at,
            backfill_run_id = EXCLUDED.backfill_run_id,
            context_summary = EXCLUDED.context_summary,
            archetype_tags  = EXCLUDED.archetype_tags,
            chosen_path     = EXCLUDED.chosen_path,
            rejected_paths  = EXCLUDED.rejected_paths,
            signal_strength = EXCLUDED.signal_strength,
            case_id         = EXCLUDED.case_id,
            embedding       = EXCLUDED.embedding,
            raw_source_ref  = EXCLUDED.raw_source_ref,
            committed       = EXCLUDED.committed
        """

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        decision_id,
                        source,
                        source_type,
                        decided_at,
                        backfill_run_id,
                        context_summary,
                        list(archetype_tags or []),
                        chosen_path,
                        Json(rejected_paths) if rejected_paths is not None else None,
                        signal_strength,
                        case_id,
                        embedding,
                        Json(raw_source_ref) if raw_source_ref is not None else None,
                        committed,
                    ),
                )
            conn.commit()

    # ── Outcome / dissent / lesson ──────────────────────────────────────

    def record_outcome(
        self,
        decision_id: str,
        observed_at: datetime,
        actual_result: str,
        chosen_path_score: float | None = None,
        metrics: dict | None = None,
    ) -> int:
        """Insert an outcome row. Returns the new outcome id."""
        sql = f"""
        INSERT INTO {self.schema}.decision_outcomes
            (decision_id, observed_at, actual_result, chosen_path_score, metrics)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        decision_id,
                        observed_at,
                        actual_result,
                        chosen_path_score,
                        Json(metrics) if metrics is not None else None,
                    ),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        return int(new_id)

    def record_dissent(
        self,
        decision_id: str,
        module: str,
        argued_for: str,
        argument: str | None = None,
    ) -> None:
        sql = f"""
        INSERT INTO {self.schema}.module_dissents
            (decision_id, module, argued_for, argument)
        VALUES (%s, %s, %s, %s)
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (decision_id, module, argued_for, argument))
            conn.commit()

    def attach_lesson(
        self,
        outcome_id: int,
        lesson: str,
        lesson_model: str,
    ) -> None:
        sql = f"""
        UPDATE {self.schema}.decision_outcomes
        SET lesson = %s,
            lesson_model = %s,
            lesson_generated_at = NOW()
        WHERE id = %s
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (lesson, lesson_model, outcome_id))
            conn.commit()

    # ── Retrieval ───────────────────────────────────────────────────────

    def retrieve_similar(
        self,
        query: str,
        top_k: int = 5,
        include_sources: list[str] | None = None,
        min_signal_strength: float = 0.0,
    ) -> list[dict]:
        """Embed the query and return the top_k structurally similar decisions.

        Results are ordered by cosine similarity against the decisions
        embedding column. The latest outcome + lesson per decision (if
        any) is joined in. Rows with ``committed=FALSE`` are excluded —
        they haven't passed privacy review.
        """
        top_k = max(1, min(int(top_k), 20))

        vec = self._compute_embedding(query, [])
        if vec is None:
            return []

        source_filter = ''
        params: list[Any] = [vec]
        if include_sources:
            source_filter = 'AND d.source_type = ANY(%s)'
            params.append(list(include_sources))

        params.append(float(min_signal_strength))
        params.append(vec)
        params.append(top_k)

        sql = f"""
        SELECT
            d.id,
            d.source,
            d.source_type,
            d.decided_at,
            d.context_summary,
            d.archetype_tags,
            d.chosen_path,
            d.rejected_paths,
            d.signal_strength,
            d.case_id,
            1.0 - (d.embedding <=> %s::vector) AS similarity,
            latest.actual_result,
            latest.chosen_path_score,
            latest.lesson,
            latest.lesson_model
        FROM {self.schema}.decisions d
        LEFT JOIN LATERAL (
            SELECT actual_result, chosen_path_score, lesson, lesson_model
            FROM {self.schema}.decision_outcomes o
            WHERE o.decision_id = d.id
            ORDER BY o.observed_at DESC
            LIMIT 1
        ) latest ON TRUE
        WHERE d.embedding IS NOT NULL
          AND d.committed = TRUE
          {source_filter}
          AND d.signal_strength >= %s
        ORDER BY d.embedding <=> %s::vector
        LIMIT %s
        """

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        results: list[dict] = []
        for row in rows:
            (
                decision_id, source, source_type, decided_at,
                context_summary, archetype_tags, chosen_path,
                rejected_paths, signal_strength, case_id, similarity,
                actual_result, chosen_path_score, lesson, lesson_model,
            ) = row
            results.append({
                'decision_id': decision_id,
                'source': source,
                'source_type': source_type,
                'decided_at': decided_at.isoformat() if decided_at else None,
                'context_summary': context_summary,
                'archetype_tags': list(archetype_tags or []),
                'chosen_path': chosen_path,
                'rejected_paths': rejected_paths,
                'signal_strength': float(signal_strength) if signal_strength is not None else None,
                'case_id': case_id,
                'similarity': float(similarity) if similarity is not None else None,
                'outcome': (
                    {
                        'actual_result': actual_result,
                        'chosen_path_score': (
                            float(chosen_path_score)
                            if chosen_path_score is not None else None
                        ),
                        'lesson': lesson,
                        'lesson_model': lesson_model,
                    }
                    if actual_result is not None else None
                ),
            })
        return results

    # ── Privacy promotion ───────────────────────────────────────────────

    def promote_pending(self, decision_ids: Iterable[str]) -> int:
        """Flip committed=FALSE rows to TRUE after privacy review.

        Returns the number of rows updated.
        """
        ids = list(decision_ids)
        if not ids:
            return 0
        sql = f"""
        UPDATE {self.schema}.decisions
        SET committed = TRUE
        WHERE id = ANY(%s) AND committed = FALSE
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ids,))
                n = cur.rowcount
            conn.commit()
        return int(n)

    # ── Backfill run ledger ─────────────────────────────────────────────

    def start_backfill_run(
        self,
        run_id: str,
        sources_requested: list[str],
        mode: str,
    ) -> None:
        """Insert a ``running`` row into ``backfill_runs``.

        Idempotent — a re-run with the same id resets ended_at/status
        to ``running`` so ``--resume`` can restart cleanly.
        """
        sql = f"""
        INSERT INTO {self.schema}.backfill_runs
            (id, sources_requested, mode, status)
        VALUES (%s, %s, %s, 'running')
        ON CONFLICT (id) DO UPDATE SET
            sources_requested = EXCLUDED.sources_requested,
            mode              = EXCLUDED.mode,
            status            = 'running',
            ended_at          = NULL
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (run_id, list(sources_requested or []), mode))
            conn.commit()

    def finish_backfill_run(
        self,
        run_id: str,
        status: str,
        counts_per_source: dict | None = None,
        claude_calls_used: int = 0,
        bulk_llm_calls_used: int = 0,
        errors: list[dict] | None = None,
    ) -> None:
        sql = f"""
        UPDATE {self.schema}.backfill_runs
        SET ended_at            = NOW(),
            status              = %s,
            counts_per_source   = %s,
            claude_calls_used   = %s,
            bulk_llm_calls_used = %s,
            errors              = %s
        WHERE id = %s
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        status,
                        Json(counts_per_source) if counts_per_source is not None else None,
                        int(claude_calls_used),
                        int(bulk_llm_calls_used),
                        Json(errors) if errors is not None else None,
                        run_id,
                    ),
                )
            conn.commit()
