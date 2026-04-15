"""task_type → model routing for cairn_delegate.

NOT to be confused with ``core/models/router.py`` — that file governs Cairn's
internal agent loop (local Ollama / DeepSeek / Claude / OpenRouter fallback).
This router is called only by the cross-module delegation surface.

Rule (D-C):
    generate                      → x-ai/grok-4-fast
    review | extract | classify   → anthropic/claude-haiku-4.5
    tier_override set             → that tier wins, unconditionally

No automatic escalation on junior-tier failure. Caller (Sonnet) decides.
"""
from __future__ import annotations

GROK_FAST = "x-ai/grok-4-fast"
HAIKU = "anthropic/claude-haiku-4.5"

VALID_TASK_TYPES = {"generate", "review", "extract", "classify"}
VALID_TIER_OVERRIDES = {"grok_fast", "haiku"}

TIER_TO_MODEL = {
    "grok_fast": GROK_FAST,
    "haiku": HAIKU,
}


def route(task_type: str, tier_override: str | None = None) -> str:
    """Return the OpenRouter model id for this call. Raises ValueError on bad input."""
    if tier_override is not None:
        if tier_override not in VALID_TIER_OVERRIDES:
            raise ValueError(
                f"tier_override must be one of {sorted(VALID_TIER_OVERRIDES)} or null; "
                f"got {tier_override!r}"
            )
        return TIER_TO_MODEL[tier_override]

    if task_type not in VALID_TASK_TYPES:
        raise ValueError(
            f"task_type must be one of {sorted(VALID_TASK_TYPES)}; got {task_type!r}"
        )

    if task_type == "generate":
        return GROK_FAST
    # review | extract | classify
    return HAIKU
