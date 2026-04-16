"""Pricing and cost computation for deek_delegate calls.

Pricing verified 2026-04-15 against OpenRouter model pages. Hardcoded here;
re-verify and bump if OpenRouter changes rates.
"""
from __future__ import annotations

from decimal import Decimal

# USD per 1M tokens.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "x-ai/grok-4-fast":           {"input_per_m_usd": 0.20, "output_per_m_usd": 0.50},
    "anthropic/claude-haiku-4.5": {"input_per_m_usd": 1.00, "output_per_m_usd": 5.00},
}

# Static conversion. Good enough for trend analysis; not invoice-grade.
USD_TO_GBP: float = 0.79


def compute_cost_gbp(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return cost in GBP for a single delegation call. Unknown model → 0.0."""
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0.0
    # Use Decimal for the small-number arithmetic, round to 6 dp to match column grain.
    cost_usd = (
        Decimal(str(pricing["input_per_m_usd"])) * Decimal(tokens_in) / Decimal(1_000_000)
        + Decimal(str(pricing["output_per_m_usd"])) * Decimal(tokens_out) / Decimal(1_000_000)
    )
    cost_gbp = cost_usd * Decimal(str(USD_TO_GBP))
    return float(round(cost_gbp, 6))
