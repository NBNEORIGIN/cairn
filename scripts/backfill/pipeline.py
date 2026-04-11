"""
Shared pipeline for the backfill importer.

Every source feeds into ``process_record``. The pipeline keeps the
source-specific logic (what to read, how to build a record) separate
from the context-summary → PII scrub → tag → write → outcome →
lesson → dissent sequence.

Design notes
------------

- **Sync, not async.** The brief sketches an async pipeline; in
  practice the backfill is a single-process foreground CLI with no
  concurrency, so async adds complexity for no benefit. All calls
  here are blocking.

- **LLM short-circuits.** If the source supplies ``context_summary``
  and ``archetype_tags`` up front (disputes, principles, synthetic),
  no Haiku call is made. The LLM budget is still the authoritative
  counter — ``bulk_used`` only ticks when an actual call happens.

- **Dry-run semantics.** In dry-run mode the pipeline computes
  everything that *would* happen but writes nothing to the database.
  It still returns a full ``ProcessResult`` so the CLI can print the
  sample. Dry-run never calls the lesson generator (no point paying
  Claude if the result is discarded).

- **Verbatim lessons.** For disputes and principles Toby's narrative
  IS the lesson. If the record sets ``verbatim_lesson``, the pipeline
  attaches it directly with ``lesson_model=toby_verbatim`` and does
  NOT invoke ``LessonGenerator``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.intel.memory import CounterfactualMemory

from .archetype_tagger import ArchetypeTagger
from .lesson_generator import LessonGenerator, OutcomeInput
from .llm_budget import BudgetExceeded
from . import privacy
from .sources.base import RawHistoricalRecord


@dataclass
class ProcessResult:
    ok: bool
    decision_id: str
    source_type: str
    summary_preview: str = ''
    tags: list[str] = field(default_factory=list)
    written: bool = False
    outcome_id: int | None = None
    lesson_attached: bool = False
    lesson_model: str | None = None
    dry_run: bool = False
    error: str | None = None


@dataclass
class RunContext:
    """Mutable per-run state passed through ``process_record``.

    Kept as a plain dataclass so tests can construct one without
    spinning up the full CLI.
    """
    run_id: str
    dry_run: bool = True
    counts_per_source: dict[str, int] = field(default_factory=dict)

    def inc(self, source: str) -> None:
        self.counts_per_source[source] = self.counts_per_source.get(source, 0) + 1


def should_generate_lesson(record: RawHistoricalRecord) -> bool:
    """Gate from the brief — strong enough signal OR a high-value source type."""
    if record.outcome is None:
        return False
    if record.signal_strength < 0.8:
        return False
    if record.source_type in {'dispute', 'b2b_quote', 'principle'}:
        return True
    score = record.outcome.chosen_path_score
    if score is not None and abs(score) >= 0.7:
        return True
    return False


def process_record(
    record: RawHistoricalRecord,
    memory: CounterfactualMemory,
    tagger: ArchetypeTagger | None,
    lesson_gen: LessonGenerator | None,
    run: RunContext,
) -> ProcessResult:
    """Summary → tag → write → outcome → lesson → dissent.

    ``tagger`` / ``lesson_gen`` may be ``None`` if the caller knows all
    records will short-circuit the LLM path (e.g. the synthetic source
    with pre-populated summaries and tags). The pipeline will raise a
    ``RuntimeError`` if a None client is then actually needed.
    """
    source_label = record.source_type

    try:
        # 1. Context summary — use the source's version or call Haiku.
        if record.context_summary:
            summary = record.context_summary
        else:
            if tagger is None:
                raise RuntimeError(
                    f'record {record.deterministic_id} needs Haiku '
                    'summarisation but no ArchetypeTagger was supplied'
                )
            raw_text = record.raw_text or record.chosen_path
            summary = tagger.summarise(raw_text, source_label=source_label)

        # 2. PII scrub — pass 1 regex. Pass 2 Haiku rewrite is wired in
        # Phase 7 when the email source lands.
        if record.needs_privacy_scrub:
            summary = privacy.scrub(summary)

        # 3. Archetype tags — use the source's or call Haiku.
        if record.archetype_tags:
            tags = list(record.archetype_tags)
        else:
            if tagger is None:
                raise RuntimeError(
                    f'record {record.deterministic_id} needs Haiku '
                    'tagging but no ArchetypeTagger was supplied'
                )
            tags = tagger.tag(summary, source_label=source_label)

        # 4. Write the decision (unless dry-run). Derived rows
        #    (outcomes, dissents) are purged first so a re-run
        #    produces the same state as a first run — the decision
        #    row upserts by id, but outcomes/dissents are INSERT-only
        #    and would otherwise accumulate.
        if not run.dry_run:
            memory.purge_outcomes_for_decision(record.deterministic_id)
            memory.purge_dissents_for_decision(record.deterministic_id)
            memory.record_historical_decision(
                decision_id=record.deterministic_id,
                source_type=record.source_type,
                decided_at=record.decided_at,
                context_summary=summary,
                archetype_tags=tags,
                chosen_path=record.chosen_path,
                rejected_paths=record.rejected_paths,
                signal_strength=record.signal_strength,
                case_id=record.case_id,
                raw_source_ref=record.raw_source_ref,
                backfill_run_id=run.run_id,
                committed=(not record.needs_privacy_review),
            )

        # 5. Outcome row (if the source supplied one).
        outcome_id: int | None = None
        if record.outcome is not None and not run.dry_run:
            outcome_id = memory.record_outcome(
                decision_id=record.deterministic_id,
                observed_at=record.outcome.observed_at,
                actual_result=record.outcome.actual_result,
                chosen_path_score=record.outcome.chosen_path_score,
                metrics=record.outcome.metrics,
            )

        # 6. Lesson — verbatim first, then LLM-generated via the gate.
        lesson_attached = False
        lesson_model: str | None = None
        if record.outcome is not None:
            if record.verbatim_lesson:
                if outcome_id is not None:
                    memory.attach_lesson(
                        outcome_id=outcome_id,
                        lesson=record.verbatim_lesson,
                        lesson_model=record.verbatim_lesson_model,
                    )
                lesson_attached = True
                lesson_model = record.verbatim_lesson_model
            elif should_generate_lesson(record) and not run.dry_run:
                if lesson_gen is None:
                    raise RuntimeError(
                        f'record {record.deterministic_id} qualifies '
                        'for a generated lesson but no LessonGenerator '
                        'was supplied'
                    )
                use_opus = (record.source_type == 'dispute')
                generated = lesson_gen.generate(
                    context=summary,
                    archetype=tags,
                    chosen_path=record.chosen_path,
                    rejected_paths=record.rejected_paths,
                    outcome=OutcomeInput(
                        actual_result=record.outcome.actual_result,
                        chosen_path_score=record.outcome.chosen_path_score,
                        metrics=record.outcome.metrics,
                    ),
                    source_label=source_label,
                    use_opus=use_opus,
                )
                if outcome_id is not None:
                    memory.attach_lesson(
                        outcome_id=outcome_id,
                        lesson=generated,
                        lesson_model=lesson_gen.model_name,
                    )
                lesson_attached = True
                lesson_model = lesson_gen.model_name

        # 7. Dissent rows (one per rejected_path).
        if not run.dry_run and record.rejected_paths:
            for rp in record.rejected_paths:
                if not isinstance(rp, dict):
                    continue
                path = rp.get('path')
                if not path:
                    continue
                memory.record_dissent(
                    decision_id=record.deterministic_id,
                    module='historical_toby',
                    argued_for=path,
                    argument=rp.get('reason'),
                )

        run.inc(source_label)

        preview = summary if len(summary) <= 200 else summary[:200] + '...'
        return ProcessResult(
            ok=True,
            decision_id=record.deterministic_id,
            source_type=record.source_type,
            summary_preview=preview,
            tags=tags,
            written=(not run.dry_run),
            outcome_id=outcome_id,
            lesson_attached=lesson_attached,
            lesson_model=lesson_model,
            dry_run=run.dry_run,
        )
    except BudgetExceeded as exc:
        return ProcessResult(
            ok=False,
            decision_id=record.deterministic_id,
            source_type=record.source_type,
            error=f'budget exceeded: {exc}',
            dry_run=run.dry_run,
        )
    except Exception as exc:
        return ProcessResult(
            ok=False,
            decision_id=record.deterministic_id,
            source_type=record.source_type,
            error=f'{type(exc).__name__}: {exc}',
            dry_run=run.dry_run,
        )
