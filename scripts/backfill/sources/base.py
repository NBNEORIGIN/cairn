"""
Shared types for backfill source adapters.

A source adapter exposes ``iter_records()`` which yields
``RawHistoricalRecord`` objects. The pipeline (scripts/backfill/pipeline.py)
takes each record, optionally calls Haiku for summarisation and
tagging, optionally calls Sonnet/Opus for a lesson, and writes the
result into ``cairn_intel.decisions`` via ``CounterfactualMemory``.

Records that pre-populate ``context_summary`` and ``archetype_tags``
skip the LLM calls entirely — useful for hand-written sources
(disputes, principles) and for the synthetic source used in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Protocol


@dataclass
class RawOutcome:
    """What actually happened after the decision — optional."""
    observed_at: datetime
    actual_result: str
    chosen_path_score: float | None = None
    metrics: dict | None = None


@dataclass
class RawHistoricalRecord:
    """Canonical input to ``pipeline.process_record``.

    Fields with sensible defaults are optional; ``deterministic_id``,
    ``source_type``, ``decided_at`` and ``chosen_path`` must always be
    set by the source.
    """
    deterministic_id: str
    source_type: str
    decided_at: datetime
    chosen_path: str

    # Optional — if both are set, the pipeline skips the Haiku calls.
    raw_text: str | None = None
    context_summary: str | None = None
    archetype_tags: list[str] | None = None

    rejected_paths: list[dict] | None = None
    signal_strength: float = 0.8
    case_id: str | None = None
    raw_source_ref: dict | None = None

    # Privacy gates — emails and b2b quotes set these to True.
    needs_privacy_scrub: bool = False
    needs_privacy_review: bool = False

    outcome: RawOutcome | None = None

    # For disputes + principles Toby's narrative IS the lesson, no LLM
    # rewrite. When set, the pipeline attaches this verbatim and does
    # NOT call the lesson generator.
    verbatim_lesson: str | None = None
    verbatim_lesson_model: str = 'toby_verbatim'


class HistoricalSource(Protocol):
    """Protocol every source adapter implements.

    Attributes
    ----------
    name : str
        Short identifier used on the CLI (``--source disputes``).
    source_type : str
        Matches ``cairn_intel.decisions.source_type`` for all records
        this adapter yields (adapters yield one source_type only).
    """

    name: str
    source_type: str

    def iter_records(self) -> Iterator[RawHistoricalRecord]:
        ...
