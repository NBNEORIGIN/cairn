"""Unit tests for core/delegation routing, cost, schema validation.

Integration test (hits OpenRouter) is marked and skipped by default.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.delegation.cost import MODEL_PRICING, USD_TO_GBP, compute_cost_gbp
from core.delegation.router import GROK_FAST, HAIKU, route


class TestRouting:
    def test_generate_routes_to_grok(self) -> None:
        assert route("generate") == GROK_FAST

    def test_review_routes_to_haiku(self) -> None:
        assert route("review") == HAIKU

    def test_extract_routes_to_haiku(self) -> None:
        assert route("extract") == HAIKU

    def test_classify_routes_to_haiku(self) -> None:
        assert route("classify") == HAIKU

    def test_tier_override_wins(self) -> None:
        assert route("review", tier_override="grok_fast") == GROK_FAST
        assert route("generate", tier_override="haiku") == HAIKU

    def test_bad_task_type_raises(self) -> None:
        with pytest.raises(ValueError):
            route("summarise")

    def test_bad_tier_override_raises(self) -> None:
        with pytest.raises(ValueError):
            route("generate", tier_override="opus")


class TestCost:
    def test_grok_cost_matches_table(self) -> None:
        # 1M in, 1M out → 0.20 + 0.50 = $0.70 USD → 0.553 GBP at 0.79 rate.
        cost = compute_cost_gbp(GROK_FAST, 1_000_000, 1_000_000)
        expected = round((0.20 + 0.50) * USD_TO_GBP, 6)
        assert cost == expected

    def test_haiku_cost_matches_table(self) -> None:
        cost = compute_cost_gbp(HAIKU, 1_000_000, 1_000_000)
        expected = round((1.00 + 5.00) * USD_TO_GBP, 6)
        assert cost == expected

    def test_small_call_cost_below_half_penny(self) -> None:
        # A realistic small call should cost well under £0.005.
        cost = compute_cost_gbp(GROK_FAST, 500, 200)
        assert 0 < cost < 0.005

    def test_unknown_model_zero_cost(self) -> None:
        assert compute_cost_gbp("anthropic/claude-opus-5", 1000, 1000) == 0.0

    def test_pricing_table_has_both_models(self) -> None:
        assert GROK_FAST in MODEL_PRICING
        assert HAIKU in MODEL_PRICING


class TestSchemaValidation:
    # _try_parse_and_validate is private to the route handler module.
    # Import lazily so test collection doesn't fail if FastAPI wiring has issues.

    def _fn(self):
        from api.routes.delegation import _try_parse_and_validate
        return _try_parse_and_validate

    def test_no_schema_is_always_valid(self) -> None:
        parsed, ok, warnings = self._fn()("anything", None)
        assert parsed is None
        assert ok is True
        assert warnings == []

    def test_valid_json_against_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["approved", "issues"],
        }
        parsed, ok, _ = self._fn()('{"approved": true, "issues": []}', schema)
        assert ok is True
        assert parsed == {"approved": True, "issues": []}

    def test_invalid_json_returns_failure(self) -> None:
        schema = {"type": "object"}
        parsed, ok, warnings = self._fn()("not json at all", schema)
        assert ok is False
        assert parsed is None
        assert any("not valid JSON" in w for w in warnings)

    def test_schema_violation_returns_failure_with_parsed(self) -> None:
        schema = {
            "type": "object",
            "properties": {"approved": {"type": "boolean"}},
            "required": ["approved"],
        }
        parsed, ok, warnings = self._fn()('{"something_else": 1}', schema)
        assert ok is False
        assert parsed == {"something_else": 1}
        assert any("schema validation failed" in w for w in warnings)

    def test_markdown_fenced_json_is_stripped(self) -> None:
        schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
        text = "```json\n{\"ok\": true}\n```"
        parsed, ok, warnings = self._fn()(text, schema)
        assert ok is True
        assert parsed == {"ok": True}
        assert any("code fences" in w for w in warnings)


@pytest.mark.integration
def test_end_to_end_openrouter_generate() -> None:
    """Hits real OpenRouter. Run manually with `pytest -m integration`.

    Requires OPENROUTER_API_KEY in the environment.
    """
    import os
    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    from core.delegation.openrouter_client import call

    result = call(
        model=GROK_FAST,
        instructions="Return the single word: pong",
        max_tokens=20,
    )
    assert result["tokens_in"] > 0
    assert result["tokens_out"] > 0
    assert isinstance(result["response"], str)
