from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class EvalPrompt:
    prompt_id: str
    prompt: str
    required_markers: list[str]
    forbidden_markers: list[str]


@dataclass(frozen=True)
class EvalResult:
    prompt_id: str
    passed: bool
    score: float
    missing_required: list[str]
    forbidden_hits: list[str]


def load_prompt_suite(path: str | Path) -> list[EvalPrompt]:
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    return [
        EvalPrompt(
            prompt_id=str(item['id']),
            prompt=str(item['prompt']),
            required_markers=[str(v) for v in item.get('required_markers', [])],
            forbidden_markers=[str(v) for v in item.get('forbidden_markers', [])],
        )
        for item in raw
    ]


def score_answer(prompt: EvalPrompt, answer: str) -> EvalResult:
    answer_lower = answer.lower()
    missing_required = [
        marker for marker in prompt.required_markers
        if marker.lower() not in answer_lower
    ]
    forbidden_hits = [
        marker for marker in prompt.forbidden_markers
        if marker.lower() in answer_lower
    ]
    total_checks = max(1, len(prompt.required_markers) + len(prompt.forbidden_markers))
    passed_checks = (
        len(prompt.required_markers) - len(missing_required)
        + len(prompt.forbidden_markers) - len(forbidden_hits)
    )
    score = round(max(0.0, min(1.0, passed_checks / total_checks)), 3)
    return EvalResult(
        prompt_id=prompt.prompt_id,
        passed=not missing_required and not forbidden_hits,
        score=score,
        missing_required=missing_required,
        forbidden_hits=forbidden_hits,
    )
