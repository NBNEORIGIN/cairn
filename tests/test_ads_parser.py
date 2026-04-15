"""
Parser tests for the Ads API v3 spAdvertisedProduct report.

Guards the dedup contract: every row must carry report_date (when Amazon
supplies it) and must use empty-string keys rather than NULLs, so the
ami_ad_daily_dedup_idx unique index catches re-syncs.
"""
from core.amazon_intel.spapi.advertising import _parse_ads_rows


def test_daily_row_carries_report_date():
    raw = [{
        "date": "2026-04-10",
        "campaignName": "SP - UK - Mar 26",
        "adGroupName": "Broad",
        "advertisedAsin": "B0SAMPLE",
        "advertisedSku": "SAMP-UK-01",
        "impressions": 1234,
        "clicks": 45,
        "cost": 12.34,
        "sales7d": 56.78,
        "purchases7d": 3,
    }]
    rows = _parse_ads_rows(raw)
    assert len(rows) == 1
    row = rows[0]
    assert row["report_date"] == "2026-04-10"
    assert row["asin"] == "B0SAMPLE"
    assert row["sku"] == "SAMP-UK-01"
    assert row["spend"] == 12.34
    assert row["sales_7d"] == 56.78
    assert row["orders_7d"] == 3
    # acos = 12.34 / 56.78 ≈ 0.2173
    assert row["acos"] is not None
    assert round(row["acos"], 2) == 0.22


def test_summary_row_without_date_leaves_report_date_none():
    """Defensive — if a SUMMARY-mode report is somehow fed to the parser,
    report_date stays None so the UPSERT and brief-query paths treat it
    as legacy and don't mix it with daily rows."""
    raw = [{
        "campaignName": "Old campaign",
        "adGroupName": "Group",
        "advertisedAsin": "B0LEGACY",
        "advertisedSku": "LEG-01",
        "impressions": 100,
        "clicks": 5,
        "cost": 1.0,
        "sales7d": 10.0,
        "purchases7d": 1,
    }]
    rows = _parse_ads_rows(raw)
    assert len(rows) == 1
    assert rows[0]["report_date"] is None


def test_missing_asin_and_sku_coalesce_to_empty_string():
    """Key columns must never be NULL — the partial unique index relies
    on non-null values to dedup correctly."""
    raw = [{
        "date": "2026-04-10",
        "campaignName": "CAMP",
        "adGroupName": "AG",
        # No advertisedAsin, no advertisedSku
        "impressions": 10,
        "clicks": 1,
        "cost": 0.50,
        "sales7d": 0,
        "purchases7d": 0,
    }]
    rows = _parse_ads_rows(raw)
    assert len(rows) == 1
    assert rows[0]["asin"] == ""
    assert rows[0]["sku"] == ""


def test_zero_sales_and_spend_produce_none_acos_roas():
    raw = [{
        "date": "2026-04-10",
        "campaignName": "C", "adGroupName": "A",
        "advertisedAsin": "B0X", "advertisedSku": "S",
        "impressions": 10, "clicks": 0,
        "cost": 0, "sales7d": 0, "purchases7d": 0,
    }]
    rows = _parse_ads_rows(raw)
    assert rows[0]["acos"] is None
    assert rows[0]["roas"] is None


def test_truncates_overlong_fields():
    raw = [{
        "date": "2026-04-10",
        "campaignName": "x" * 600,
        "adGroupName": "y" * 600,
        "advertisedAsin": "Z" * 50,  # Amazon ASINs are 10 chars, but defend
        "advertisedSku": "S" * 200,
        "impressions": 1, "clicks": 0,
        "cost": 0, "sales7d": 0, "purchases7d": 0,
    }]
    rows = _parse_ads_rows(raw)
    assert len(rows[0]["campaign_name"]) == 500
    assert len(rows[0]["ad_group_name"]) == 500
    assert len(rows[0]["asin"]) == 20
    assert len(rows[0]["sku"]) == 100
