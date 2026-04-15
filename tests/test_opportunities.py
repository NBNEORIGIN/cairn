"""
Unit tests for the opportunities module.

Pure functions only — no DB, no LLM. The DB loader (fetch_listing_content)
and the async Claude wrapper (assess_listing_quality) are covered by
integration tests once real data lands.
"""
import pytest

from core.amazon_intel.margin.opportunities import (
    _parse_assessment_json,
    _rec_from_dict,
    rank_opportunities,
    score_recommendation,
    SCALE_WEIGHT,
)
from core.amazon_intel.margin.quartile_brief import Recommendation


def _rec(
    *,
    action="REDUCE",
    spend=100.0,
    ad_sales=100.0,
    total_revenue=500.0,
    units=30,
    current_acos=1.0,
    recommended_acos=0.2,
    organic_rate=0.5,
) -> Recommendation:
    return Recommendation(
        asin="B0TEST",
        sku="SKU-1",
        m_number="M0001",
        account_name="Origin Trading",
        country_code="UK",
        action=action,
        reason="test",
        caveats=[],
        spend=spend,
        ad_sales=ad_sales,
        total_revenue=total_revenue,
        units=units,
        current_acos=current_acos,
        current_tacos=None,
        organic_rate=organic_rate,
        recommended_acos=recommended_acos,
    )


# ── score_recommendation — waste branch ──────────────────────────────────────


def test_waste_matches_overspend_above_target():
    """REDUCE case — spend £100 on £100 ad-sales (ACOS 100%) against a 20%
    target. Waste = 100 − 0.2×100 = £80."""
    comp = score_recommendation(_rec(spend=100, ad_sales=100, recommended_acos=0.2))
    assert comp.waste_gbp == 80.0
    assert comp.scale_gbp == 0.0
    # revenue 500 → log10(501) ≈ 2.700
    assert 2.69 < comp.revenue_weight < 2.71
    assert comp.opportunity_score == pytest.approx(80.0 * comp.revenue_weight, rel=1e-3)


def test_no_waste_when_acos_at_or_below_target():
    comp = score_recommendation(
        _rec(action="HOLD", spend=100, ad_sales=500, current_acos=0.2, recommended_acos=0.2),
    )
    assert comp.waste_gbp == 0.0
    assert comp.scale_gbp == 0.0
    assert comp.opportunity_score == 0.0


def test_waste_zero_when_ad_sales_zero():
    """No ad sales means we can't compute waste — would require division
    by zero to derive the target spend line."""
    comp = score_recommendation(_rec(spend=50, ad_sales=0, current_acos=None))
    assert comp.waste_gbp == 0.0
    assert comp.opportunity_score == 0.0


def test_waste_zero_when_recommended_acos_missing():
    comp = score_recommendation(_rec(recommended_acos=None))
    assert comp.waste_gbp == 0.0


# ── score_recommendation — scale branch ─────────────────────────────────────


def test_scale_headroom_only_fires_for_increase_action():
    """A REDUCE row with room to grow ACOS still does NOT get a scale
    component — scale is reserved for INCREASE candidates."""
    comp = score_recommendation(
        _rec(action="REDUCE", spend=10, ad_sales=200, current_acos=0.05, recommended_acos=0.2),
    )
    assert comp.scale_gbp == 0.0


def test_scale_headroom_for_increase_is_discounted():
    """INCREASE — spend £10 at 5% ACOS on £200 ad sales. Target 20% →
    target ad sales = 10 / 0.2 = £50. Headroom = 50 − 200 = negative,
    clamped to 0. Use a more realistic case."""
    comp = score_recommendation(
        _rec(
            action="INCREASE",
            spend=10,
            ad_sales=40,              # current ACOS 25%
            recommended_acos=0.5,     # target ACOS 50%
            current_acos=0.25,
        ),
    )
    # target ad sales = 10 / 0.5 = 20 → headroom = max(0, 20 − 40) = 0
    assert comp.scale_gbp == 0.0

    comp2 = score_recommendation(
        _rec(
            action="INCREASE",
            spend=10,
            ad_sales=20,              # current ACOS 50%
            recommended_acos=1.0,     # target ACOS 100%
            current_acos=0.5,
        ),
    )
    # target ad sales = 10 / 1.0 = 10 → headroom = max(0, 10 − 20) = 0
    assert comp2.scale_gbp == 0.0

    # Actual headroom case — current 10% ACOS, target 25% → target ad sales
    # = 10 / 0.25 = 40; headroom = max(0, 40 − 20) = 20; × SCALE_WEIGHT.
    comp3 = score_recommendation(
        _rec(
            action="INCREASE",
            spend=10,
            ad_sales=20,
            current_acos=0.5,
            recommended_acos=0.25,
        ),
    )
    # NOTE: this is a REDUCE-shaped math case (current > target), but the
    # classify layer would mark it INCREASE only if current < target. The
    # score function is agnostic to that — it just computes the arithmetic.
    assert comp3.scale_gbp == (40 - 20) * SCALE_WEIGHT


def test_new_product_caveat_zeroes_score():
    """A row tagged as new-product (caveat applied by quartile_brief) must
    never show up in opportunities regardless of its waste numbers."""
    from core.amazon_intel.margin.quartile_brief import NEW_PRODUCT_CAVEAT_PREFIX
    rec = _rec(
        action="HOLD",
        spend=500, ad_sales=100, total_revenue=10000,
        current_acos=5.0, recommended_acos=0.2,
    )
    # High waste would normally produce a big score
    raw_comp = score_recommendation(rec)
    assert raw_comp.opportunity_score > 0
    # Now mark it as a new product
    rec.caveats = [f"{NEW_PRODUCT_CAVEAT_PREFIX} (M1500 >= M1000) — establishment"]
    new_comp = score_recommendation(rec)
    assert new_comp.waste_gbp == 0.0
    assert new_comp.scale_gbp == 0.0
    assert new_comp.opportunity_score == 0.0


def test_revenue_weight_falls_back_when_no_revenue_data():
    """Missing total revenue shouldn't zero the score — use fallback 0.3
    so opportunities still surface while orders sync catches up."""
    comp = score_recommendation(_rec(total_revenue=0.0))
    assert comp.revenue_weight == 0.3


# ── rank_opportunities ───────────────────────────────────────────────────────


def test_rank_opportunities_sorts_desc_and_drops_zero_score():
    recs = [
        {  # high waste + high revenue → high score
            "asin": "A1", "sku": "S1", "m_number": None,
            "account_name": "X", "country_code": "UK",
            "action": "REDUCE", "reason": "r", "caveats": [],
            "spend": 500, "ad_sales": 500, "total_revenue": 10000,
            "units": 100, "current_acos": 1.0, "current_tacos": None,
            "organic_rate": 0.2, "recommended_acos": 0.2,
        },
        {  # zero score — at target
            "asin": "A2", "sku": "S2", "m_number": None,
            "account_name": "X", "country_code": "UK",
            "action": "HOLD", "reason": "r", "caveats": [],
            "spend": 10, "ad_sales": 50, "total_revenue": 200,
            "units": 5, "current_acos": 0.2, "current_tacos": None,
            "organic_rate": 0.3, "recommended_acos": 0.2,
        },
        {  # mid waste, smaller revenue
            "asin": "A3", "sku": "S3", "m_number": None,
            "account_name": "X", "country_code": "UK",
            "action": "REDUCE", "reason": "r", "caveats": [],
            "spend": 50, "ad_sales": 100, "total_revenue": 300,
            "units": 10, "current_acos": 0.5, "current_tacos": None,
            "organic_rate": 0.2, "recommended_acos": 0.2,
        },
    ]
    ranked = rank_opportunities(recs, limit=10)
    assert [r["asin"] for r in ranked] == ["A1", "A3"]  # A2 dropped (score 0)
    assert ranked[0]["opportunity_score"] > ranked[1]["opportunity_score"]
    assert "score_components" in ranked[0]
    assert "waste_gbp" in ranked[0]["score_components"]


def test_rank_opportunities_respects_limit():
    recs = [
        {
            "asin": f"A{i}", "sku": f"S{i}", "m_number": None,
            "account_name": "X", "country_code": "UK",
            "action": "REDUCE", "reason": "r", "caveats": [],
            "spend": 100 + i, "ad_sales": 100, "total_revenue": 500 + i,
            "units": 10, "current_acos": 1.0, "current_tacos": None,
            "organic_rate": 0.2, "recommended_acos": 0.2,
        }
        for i in range(5)
    ]
    ranked = rank_opportunities(recs, limit=3)
    assert len(ranked) == 3


# ── _rec_from_dict roundtrip ─────────────────────────────────────────────────


def test_rec_from_dict_handles_missing_fields():
    """Defensive parsing — a dict missing some optional fields should still
    produce a usable Recommendation."""
    rec = _rec_from_dict({"asin": "B0X", "action": "HOLD"})
    assert rec.asin == "B0X"
    assert rec.action == "HOLD"
    assert rec.spend == 0.0
    assert rec.current_acos is None


# ── _parse_assessment_json — happy path ──────────────────────────────────────


def test_parse_assessment_plain_json():
    raw = (
        '{"quality_score": 7, "likely_correlates": true, '
        '"verdict": "listing likely explains ACOS", '
        '"issues": ["title missing size"], "fixes": ["add size to title"]}'
    )
    parsed = _parse_assessment_json(raw)
    assert parsed is not None
    assert parsed["quality_score"] == 7
    assert parsed["likely_correlates"] is True
    assert parsed["issues"] == ["title missing size"]
    assert parsed["fixes"] == ["add size to title"]


def test_parse_assessment_strips_markdown_fence():
    """Claude sometimes wraps JSON in ```json fences — strip and parse."""
    raw = (
        "```json\n"
        '{"quality_score": 4, "likely_correlates": false, '
        '"verdict": "mixed", "issues": [], "fixes": []}\n'
        "```"
    )
    parsed = _parse_assessment_json(raw)
    assert parsed is not None
    assert parsed["quality_score"] == 4
    assert parsed["likely_correlates"] is False


def test_parse_assessment_strips_unlabelled_fence():
    raw = "```\n{\"quality_score\": 3, \"verdict\": \"x\"}\n```"
    parsed = _parse_assessment_json(raw)
    assert parsed is not None
    assert parsed["quality_score"] == 3


def test_parse_assessment_caps_list_lengths():
    """issues/fixes beyond 6 entries should be clipped so the UI doesn't
    drown in a runaway LLM response."""
    issues = [f"issue-{i}" for i in range(20)]
    raw = (
        '{"quality_score": 5, "likely_correlates": true, "verdict": "x", '
        f'"issues": {issues!r}, "fixes": []}}'
    ).replace("'", '"')
    parsed = _parse_assessment_json(raw)
    assert parsed is not None
    assert len(parsed["issues"]) == 6


# ── _parse_assessment_json — failure modes ──────────────────────────────────


def test_parse_assessment_returns_none_on_empty():
    assert _parse_assessment_json("") is None
    assert _parse_assessment_json("   ") is None


def test_parse_assessment_returns_none_on_non_json():
    assert _parse_assessment_json("the listing looks fine overall.") is None


def test_parse_assessment_returns_none_on_array_at_root():
    """Model returned a JSON array instead of an object — reject."""
    assert _parse_assessment_json('[{"quality_score": 5}]') is None


def test_parse_assessment_missing_keys_get_defaults():
    """Model returned partial JSON — missing keys coerce to safe defaults
    rather than raising."""
    parsed = _parse_assessment_json('{"quality_score": 6}')
    assert parsed is not None
    assert parsed["quality_score"] == 6
    assert parsed["verdict"] == ""
    assert parsed["issues"] == []
    assert parsed["fixes"] == []
