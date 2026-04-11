"""
Shared LLM call counter and budget enforcer for the backfill importer.

Every Claude / Haiku call goes through a ``consume_*`` method so that a
runaway source iterator can't quietly burn through the budget. Raises
``BudgetExceeded`` when a call would cross the cap; the caller decides
whether to skip the record, fall back, or abort the run.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    """Raised when a budget cap has been hit."""


@dataclass
class LLMBudget:
    """Per-run call budget.

    Defaults mirror ``scripts/backfill/run.py --help``:
        max_sonnet: 200 Sonnet calls (lesson generator default model)
        max_opus:    50 Opus calls   (lesson generator upgraded model)
        max_bulk:  5000 Haiku calls  (summarise + tag + privacy rewrite)
    """

    max_sonnet: int = 200
    max_opus: int = 50
    max_bulk: int = 5000

    sonnet_used: int = 0
    opus_used: int = 0
    bulk_used: int = 0

    # Per-source counts so the post-run report can explain where the
    # budget went without forcing the caller to pass the source name
    # through every function.
    bulk_by_source: dict[str, int] = field(default_factory=dict)
    sonnet_by_source: dict[str, int] = field(default_factory=dict)
    opus_by_source: dict[str, int] = field(default_factory=dict)

    def consume_bulk(self, source: str = 'unknown') -> None:
        if self.bulk_used >= self.max_bulk:
            raise BudgetExceeded(
                f'Haiku budget exhausted after {self.bulk_used} calls '
                f'(max {self.max_bulk})'
            )
        self.bulk_used += 1
        self.bulk_by_source[source] = self.bulk_by_source.get(source, 0) + 1

    def consume_sonnet(self, source: str = 'unknown') -> None:
        if self.sonnet_used >= self.max_sonnet:
            raise BudgetExceeded(
                f'Sonnet budget exhausted after {self.sonnet_used} calls '
                f'(max {self.max_sonnet})'
            )
        self.sonnet_used += 1
        self.sonnet_by_source[source] = self.sonnet_by_source.get(source, 0) + 1

    def consume_opus(self, source: str = 'unknown') -> None:
        if self.opus_used >= self.max_opus:
            raise BudgetExceeded(
                f'Opus budget exhausted after {self.opus_used} calls '
                f'(max {self.max_opus})'
            )
        self.opus_used += 1
        self.opus_by_source[source] = self.opus_by_source.get(source, 0) + 1

    def remaining_bulk(self) -> int:
        return max(0, self.max_bulk - self.bulk_used)

    def remaining_sonnet(self) -> int:
        return max(0, self.max_sonnet - self.sonnet_used)

    def remaining_opus(self) -> int:
        return max(0, self.max_opus - self.opus_used)

    def summary(self) -> dict:
        return {
            'sonnet_used': self.sonnet_used,
            'sonnet_max': self.max_sonnet,
            'opus_used': self.opus_used,
            'opus_max': self.max_opus,
            'bulk_used': self.bulk_used,
            'bulk_max': self.max_bulk,
            'bulk_by_source': dict(self.bulk_by_source),
            'sonnet_by_source': dict(self.sonnet_by_source),
            'opus_by_source': dict(self.opus_by_source),
        }
