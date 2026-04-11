"""
Source 5 — disputes.

Reads ``scripts/backfill/data/disputes.yml`` (authored by Toby, not
auto-generated) and yields one ``RawHistoricalRecord`` per phase of
each dispute case. All phases of a case share a ``case_id`` so the
retrieval layer can pull them together as a single narrative.

Key invariants from the brief (section 2.6):

- ``signal_strength = 0.95`` on every row. These are Toby's own
  narratives of known-outcome cases — strongest possible historical
  signal.
- ``source_type = 'dispute'`` for all rows from this source.
- ``chosen_path_score`` comes straight from the YAML.
- The final phase of each case carries ``lessons_in_your_own_words``
  as its ``verbatim_lesson`` (``lesson_model='toby_verbatim'``).
  **The pipeline does NOT call Claude to rewrite Toby's lessons.**
- **Exception**: if Toby left ``lessons_in_your_own_words`` empty for
  a case, the pipeline upgrades the lesson generator to Opus (not
  Sonnet) for that single call. These are the crown jewels.

YAML schema (per the brief, section 2.5):

    - case_id: evri-clarion-2024
      parties: [NBNE, Evri, Clarion]
      initial_claim_gbp: 1705
      final_settlement_gbp: 350
      phases:
        - phase: initial_response
          decided_at: 2024-XX-XX
          context: |
            Full narrative in Toby's own words.
          chosen_path: "Rejected the first settlement offer because..."
          rejected_alternatives:
            - path: "Accept £X immediately"
              reason: "Would have set precedent..."
          outcome: |
            What actually happened next.
          chosen_path_score: 0.8
          metrics:
            settlement_gbp: 350
            days_to_resolve: 45
      lessons_in_your_own_words: |
        What you actually learned from this case.

Phases are ordered in the YAML as decided; the last phase of a case
receives the case-level ``lessons_in_your_own_words`` as its
verbatim lesson.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from .base import HistoricalSource, RawHistoricalRecord, RawOutcome


class DisputeYamlError(ValueError):
    """Raised when disputes.yml is malformed in a way that should halt the run."""


class DisputesSource:
    """YAML-backed historical source for contested commercial cases."""

    name: str = 'disputes'
    source_type: str = 'dispute'

    def __init__(self, yaml_path: Path):
        self.yaml_path = Path(yaml_path)
        if not self.yaml_path.exists():
            raise DisputeYamlError(
                f'disputes.yml not found at {self.yaml_path}. '
                'This file is authored by Toby — the importer cannot '
                'generate dispute narratives synthetically.'
            )

    def iter_records(self) -> Iterator[RawHistoricalRecord]:
        raw = yaml.safe_load(self.yaml_path.read_text(encoding='utf-8'))
        if raw is None:
            return  # empty file — nothing to do
        if not isinstance(raw, list):
            raise DisputeYamlError(
                f'{self.yaml_path} must be a YAML list of cases, '
                f'got {type(raw).__name__}'
            )

        for case in raw:
            yield from _iter_case(case, self.yaml_path)


def _iter_case(case: Any, yaml_path: Path) -> Iterator[RawHistoricalRecord]:
    if not isinstance(case, dict):
        raise DisputeYamlError(
            f'{yaml_path}: every case must be a mapping, got {type(case).__name__}'
        )

    case_id = case.get('case_id')
    if not case_id or not isinstance(case_id, str):
        raise DisputeYamlError(
            f'{yaml_path}: case missing required string field case_id'
        )

    phases = case.get('phases')
    if not isinstance(phases, list) or not phases:
        raise DisputeYamlError(
            f"{yaml_path}: case '{case_id}' must have a non-empty phases list"
        )

    case_level_lesson = case.get('lessons_in_your_own_words')
    if case_level_lesson is not None and not isinstance(case_level_lesson, str):
        raise DisputeYamlError(
            f"{yaml_path}: case '{case_id}' lessons_in_your_own_words "
            'must be a string if present'
        )
    if isinstance(case_level_lesson, str):
        case_level_lesson = case_level_lesson.strip() or None

    parties = case.get('parties') or []
    initial_claim = case.get('initial_claim_gbp')
    final_settlement = case.get('final_settlement_gbp')

    last_idx = len(phases) - 1
    for i, phase in enumerate(phases):
        is_last_phase = (i == last_idx)
        yield _build_phase_record(
            case=case,
            phase=phase,
            case_id=case_id,
            phase_index=i,
            is_last_phase=is_last_phase,
            case_level_lesson=case_level_lesson if is_last_phase else None,
            parties=parties,
            initial_claim=initial_claim,
            final_settlement=final_settlement,
            yaml_path=yaml_path,
        )


def _build_phase_record(
    case: dict,
    phase: Any,
    case_id: str,
    phase_index: int,
    is_last_phase: bool,
    case_level_lesson: str | None,
    parties: list,
    initial_claim: Any,
    final_settlement: Any,
    yaml_path: Path,
) -> RawHistoricalRecord:
    if not isinstance(phase, dict):
        raise DisputeYamlError(
            f"{yaml_path}: case '{case_id}' phase {phase_index} must be a mapping"
        )

    phase_name = phase.get('phase') or f'phase_{phase_index}'
    if not isinstance(phase_name, str):
        raise DisputeYamlError(
            f"{yaml_path}: case '{case_id}' phase {phase_index} 'phase' must be a string"
        )

    context_raw = phase.get('context')
    if not isinstance(context_raw, str) or not context_raw.strip():
        raise DisputeYamlError(
            f"{yaml_path}: case '{case_id}' phase '{phase_name}' missing context"
        )
    context = context_raw.strip()

    chosen_path = phase.get('chosen_path')
    if not isinstance(chosen_path, str) or not chosen_path.strip():
        raise DisputeYamlError(
            f"{yaml_path}: case '{case_id}' phase '{phase_name}' missing chosen_path"
        )
    chosen_path = chosen_path.strip()

    decided_at = _coerce_date(
        phase.get('decided_at'),
        where=f"case '{case_id}' phase '{phase_name}'",
        yaml_path=yaml_path,
    )

    rejected_paths = _coerce_rejected(
        phase.get('rejected_alternatives'),
        where=f"case '{case_id}' phase '{phase_name}'",
        yaml_path=yaml_path,
    )

    outcome_text = phase.get('outcome')
    score = phase.get('chosen_path_score')
    metrics = phase.get('metrics')
    if metrics is not None and not isinstance(metrics, dict):
        raise DisputeYamlError(
            f"{yaml_path}: case '{case_id}' phase '{phase_name}' metrics must be a mapping"
        )

    outcome: RawOutcome | None = None
    if isinstance(outcome_text, str) and outcome_text.strip():
        outcome = RawOutcome(
            observed_at=decided_at,  # best estimate — YAML doesn't split these
            actual_result=outcome_text.strip(),
            chosen_path_score=float(score) if score is not None else None,
            metrics=metrics,
        )

    # Verbatim lesson: only the last phase of the case receives the
    # case-level narrative lesson. If missing, the pipeline picks it up
    # via the should_generate_lesson gate + use_opus route.
    verbatim_lesson: str | None = None
    if is_last_phase and case_level_lesson:
        verbatim_lesson = case_level_lesson

    deterministic_id = f'backfill_dispute_{case_id}_{phase_name}'

    raw_source_ref: dict = {
        'yaml_path': str(yaml_path),
        'case_id': case_id,
        'phase': phase_name,
        'phase_index': phase_index,
    }
    if parties:
        raw_source_ref['parties'] = list(parties)
    if initial_claim is not None:
        raw_source_ref['initial_claim_gbp'] = initial_claim
    if final_settlement is not None:
        raw_source_ref['final_settlement_gbp'] = final_settlement

    return RawHistoricalRecord(
        deterministic_id=deterministic_id,
        source_type='dispute',
        decided_at=decided_at,
        chosen_path=chosen_path,
        context_summary=context,
        # archetype_tags intentionally NOT set — disputes go through
        # Haiku tagging so the taxonomy stays source-agnostic.
        archetype_tags=None,
        rejected_paths=rejected_paths,
        signal_strength=0.95,
        case_id=case_id,
        raw_source_ref=raw_source_ref,
        # Disputes are about business counterparties, not private
        # individuals — the brief says they don't need PII scrubbing.
        needs_privacy_scrub=False,
        needs_privacy_review=False,
        outcome=outcome,
        verbatim_lesson=verbatim_lesson,
        verbatim_lesson_model='toby_verbatim',
    )


def _coerce_date(raw: Any, where: str, yaml_path: Path) -> datetime:
    """Normalise the YAML decided_at value to a tz-aware datetime.

    PyYAML parses ISO date / datetime strings automatically, so we
    accept ``datetime``, ``date``, or a string the user can still
    quote freely.
    """
    if raw is None:
        raise DisputeYamlError(
            f'{yaml_path}: {where} missing decided_at'
        )
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    # PyYAML returns plain dates for bare YYYY-MM-DD values.
    import datetime as _dt
    if isinstance(raw, _dt.date):
        return datetime.combine(raw, time(0, 0), tzinfo=timezone.utc)
    if isinstance(raw, str):
        cleaned = raw.strip()
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError as exc:
            raise DisputeYamlError(
                f"{yaml_path}: {where} decided_at '{raw}' is not a valid "
                'ISO date/datetime'
            ) from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise DisputeYamlError(
        f'{yaml_path}: {where} decided_at must be a date or ISO string, '
        f'got {type(raw).__name__}'
    )


def _coerce_rejected(
    raw: Any,
    where: str,
    yaml_path: Path,
) -> list[dict] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise DisputeYamlError(
            f'{yaml_path}: {where} rejected_alternatives must be a list'
        )
    out: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise DisputeYamlError(
                f'{yaml_path}: {where} rejected_alternatives[{i}] must be a mapping'
            )
        path = item.get('path')
        if not isinstance(path, str) or not path.strip():
            raise DisputeYamlError(
                f'{yaml_path}: {where} rejected_alternatives[{i}].path is required'
            )
        entry: dict = {'path': path.strip()}
        reason = item.get('reason')
        if isinstance(reason, str) and reason.strip():
            entry['reason'] = reason.strip()
        out.append(entry)
    return out or None
