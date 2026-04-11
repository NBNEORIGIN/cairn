"""
Claude Sonnet / Opus wrapper for generating actionable lessons.

A lesson is a short, actionable sentence (or two) that captures what
should be done differently next time, given a decision, its outcome,
and any rejected alternatives. It is the pay-off of the whole
counterfactual memory pipeline — everything else (context, tags,
similarity) exists so the right lesson can be surfaced on the right
future question.

Budget is enforced by ``LLMBudget``. Sonnet is the default; Opus is
only used when the caller explicitly opts in (reserved for dispute
cases per the brief).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .llm_budget import LLMBudget


_LESSON_SYSTEM = (
    'You are a business elder reflecting on a past decision to write '
    'a single actionable lesson for future-you. You will receive: the '
    'situation, the archetype tags, the path chosen, any rejected '
    'alternatives, and what actually happened. '
    'Return ONE or TWO plain sentences that a business operator could '
    'apply to a new situation with the same archetype. Be specific. '
    'Avoid cliches. Do not summarise the past decision — extract the '
    'rule that makes the next decision better. No preamble, no '
    'numbering, no quotes, no sign-off.'
)


@dataclass
class OutcomeInput:
    """Lightweight shape the lesson generator consumes.

    Kept separate from ``sources.base.RawOutcome`` so the generator
    does not depend on the sources package.
    """
    actual_result: str
    chosen_path_score: float | None = None
    metrics: dict | None = None


class LessonGenerator:
    """Sonnet/Opus wrapper with budget enforcement."""

    def __init__(
        self,
        budget: LLMBudget,
        api_key: str | None = None,
        default_model: str | None = None,
        opus_model: str | None = None,
    ):
        self.budget = budget
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY', '')
        self.default_model = default_model or os.getenv(
            'CLAUDE_MODEL', 'claude-sonnet-4-6'
        )
        self.opus_model = opus_model or os.getenv(
            'CLAUDE_OPUS_MODEL', 'claude-opus-4-6'
        )
        self._client: Any = None
        self._last_model_used: str = self.default_model

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    @property
    def model_name(self) -> str:
        """The model used by the most recent ``generate`` call."""
        return self._last_model_used

    def generate(
        self,
        context: str,
        archetype: list[str],
        chosen_path: str,
        rejected_paths: list[dict] | None,
        outcome: OutcomeInput,
        source_label: str = 'unknown',
        use_opus: bool = False,
    ) -> str:
        """Generate a lesson, consuming one sonnet or opus budget slot."""
        if use_opus:
            self.budget.consume_opus(source=source_label)
            model = self.opus_model
        else:
            self.budget.consume_sonnet(source=source_label)
            model = self.default_model
        self._last_model_used = model

        prompt = _format_lesson_prompt(
            context=context,
            archetype=archetype,
            chosen_path=chosen_path,
            rejected_paths=rejected_paths,
            outcome=outcome,
        )

        client = self._get_client()
        resp = client.messages.create(
            model=model,
            max_tokens=260,
            system=_LESSON_SYSTEM,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return _first_text(resp).strip()


def _format_lesson_prompt(
    context: str,
    archetype: list[str],
    chosen_path: str,
    rejected_paths: list[dict] | None,
    outcome: OutcomeInput,
) -> str:
    tag_txt = ', '.join(archetype) if archetype else '(none)'
    rejected_txt = ''
    if rejected_paths:
        lines = []
        for rp in rejected_paths:
            if not isinstance(rp, dict):
                continue
            path = rp.get('path', '').strip()
            reason = rp.get('reason', '').strip()
            if path and reason:
                lines.append(f'  - {path} — rejected because: {reason}')
            elif path:
                lines.append(f'  - {path}')
        rejected_txt = '\n'.join(lines) if lines else '(none)'
    else:
        rejected_txt = '(none)'

    score_txt = (
        f"{outcome.chosen_path_score:+.2f}"
        if outcome.chosen_path_score is not None else 'unscored'
    )
    metrics_txt = ''
    if outcome.metrics:
        metrics_txt = '\n'.join(
            f'  - {k}: {v}' for k, v in outcome.metrics.items()
        )
    else:
        metrics_txt = '(none)'

    return (
        f'SITUATION:\n{context}\n\n'
        f'ARCHETYPE: {tag_txt}\n\n'
        f'CHOSEN PATH:\n{chosen_path}\n\n'
        f'REJECTED ALTERNATIVES:\n{rejected_txt}\n\n'
        f'OUTCOME:\n{outcome.actual_result}\n\n'
        f'CHOSEN PATH SCORE: {score_txt}\n\n'
        f'METRICS:\n{metrics_txt}\n\n'
        'Write the lesson now.'
    )


def _first_text(response: Any) -> str:
    try:
        for block in response.content:
            if getattr(block, 'type', '') == 'text':
                return block.text
    except Exception:
        pass
    return ''
