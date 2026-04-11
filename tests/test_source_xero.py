"""
Tests for ``scripts.backfill.sources.xero``.

Uses a SQLite shim is impractical (the source emits postgres
``date_trunc`` SQL) so we point at the real Ledger DB when it is
available and skip otherwise. A unit test on the record-building
logic runs without any DB at all.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest


# ── Pure unit tests (no DB) ────────────────────────────────────────────


def test_build_record_with_outcome_attaches_margin_delta():
    from scripts.backfill.sources.xero import MonthlyPL, _build_record

    jan = MonthlyPL(
        month=datetime(2025, 1, 1, tzinfo=timezone.utc),
        tx_count=15,
        gross_revenue=Decimal('50000'),
        net_revenue=Decimal('26000'),
        channel_fees=Decimal('8000'),
        ad_fees=Decimal('2000'),
        postage_cost=Decimal('1500'),
        expenditure=Decimal('20000'),
        top_channels=[('amazon_uk', Decimal('15000')), ('etsy', Decimal('6000'))],
    )
    feb = MonthlyPL(
        month=datetime(2025, 2, 1, tzinfo=timezone.utc),
        tx_count=14,
        gross_revenue=Decimal('35000'),
        net_revenue=Decimal('25000'),
        channel_fees=Decimal('6000'),
        ad_fees=Decimal('2000'),
        postage_cost=Decimal('1000'),
        expenditure=Decimal('18000'),
        top_channels=[('amazon_uk', Decimal('14000'))],
    )

    record = _build_record(jan, feb)
    assert record.deterministic_id == 'backfill_xero_2025_01'
    assert record.source_type == 'xero'
    assert record.signal_strength == 0.9
    assert '£50,000' in record.context_summary
    assert 'amazon_uk' in record.context_summary
    # Jan net/gross = 26000/50000 = 52.0%
    assert '52.0%' in record.context_summary

    assert record.outcome is not None
    metrics = record.outcome.metrics
    assert metrics['month'] == '2025-01'
    # Jan net/gross = 52.0%
    # Feb net/gross = 25000/35000 ≈ 71.43%
    # delta ≈ +19.43 pp
    assert abs(metrics['margin_delta_pp'] - 19.43) < 0.1
    # Score = 19.43 / 15.0 clamped to 1.0.
    assert record.outcome.chosen_path_score == pytest.approx(1.0)


def test_build_record_without_next_month_has_no_outcome():
    from scripts.backfill.sources.xero import MonthlyPL, _build_record
    last = MonthlyPL(
        month=datetime(2026, 3, 1, tzinfo=timezone.utc),
        tx_count=10,
        gross_revenue=Decimal('40000'),
        net_revenue=Decimal('22000'),
        channel_fees=Decimal('5000'),
        ad_fees=Decimal('1500'),
        postage_cost=Decimal('800'),
        expenditure=Decimal('16000'),
        top_channels=[],
    )
    record = _build_record(last, None)
    assert record.outcome is None
    assert record.deterministic_id == 'backfill_xero_2026_03'


def test_score_passes_gate_on_11pp_margin_delta():
    """Gate: |margin_delta| > 10pp triggers Sonnet. 11pp → score 0.73 > 0.7."""
    from scripts.backfill.sources.xero import MonthlyPL, _build_record
    from scripts.backfill.pipeline import should_generate_lesson

    # Month 1: gross 100k net 50k → net/gross 50%
    good = MonthlyPL(
        month=datetime(2025, 1, 1, tzinfo=timezone.utc),
        tx_count=10, gross_revenue=Decimal('100000'),
        net_revenue=Decimal('50000'),
        channel_fees=Decimal('0'), ad_fees=Decimal('0'),
        postage_cost=Decimal('0'),
        expenditure=Decimal('0'),
        top_channels=[],
    )
    # Month 2: gross 100k net 61k → net/gross 61% (+11pp)
    better = MonthlyPL(
        month=datetime(2025, 2, 1, tzinfo=timezone.utc),
        tx_count=10, gross_revenue=Decimal('100000'),
        net_revenue=Decimal('61000'),
        channel_fees=Decimal('0'), ad_fees=Decimal('0'),
        postage_cost=Decimal('0'),
        expenditure=Decimal('0'),
        top_channels=[],
    )
    record = _build_record(good, better)
    assert record.outcome.chosen_path_score > 0.7
    assert should_generate_lesson(record) is True


def test_score_fails_gate_on_9pp_margin_delta():
    from scripts.backfill.sources.xero import MonthlyPL, _build_record
    from scripts.backfill.pipeline import should_generate_lesson

    base = MonthlyPL(
        month=datetime(2025, 1, 1, tzinfo=timezone.utc),
        tx_count=10, gross_revenue=Decimal('100000'),
        net_revenue=Decimal('50000'),
        channel_fees=Decimal('0'), ad_fees=Decimal('0'),
        postage_cost=Decimal('0'),
        expenditure=Decimal('0'),
        top_channels=[],
    )
    slightly_better = MonthlyPL(
        month=datetime(2025, 2, 1, tzinfo=timezone.utc),
        tx_count=10, gross_revenue=Decimal('100000'),
        net_revenue=Decimal('59000'),  # +9pp
        channel_fees=Decimal('0'), ad_fees=Decimal('0'),
        postage_cost=Decimal('0'),
        expenditure=Decimal('0'),
        top_channels=[],
    )
    record = _build_record(base, slightly_better)
    assert abs(record.outcome.chosen_path_score) < 0.7
    assert should_generate_lesson(record) is False


# ── Integration test against the real Ledger DB ────────────────────────


def _ledger_reachable() -> bool:
    import psycopg2
    try:
        conn = psycopg2.connect(
            os.getenv(
                'LEDGER_DATABASE_URL',
                'postgresql://postgres:postgres123@localhost:5432/ledger',
            ),
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _ledger_reachable(),
    reason='Ledger DB not reachable',
)
def test_xero_source_reads_real_ledger():
    from scripts.backfill.sources.xero import XeroSource
    records = list(XeroSource().iter_records())
    # At least a handful of months — the exact count depends on how
    # many calendar months have revenue_transactions rows (the table
    # has gaps in months where no transactions were imported).
    assert len(records) >= 3, f'expected >=3 monthly records, got {len(records)}'
    assert all(r.source_type == 'xero' for r in records)
    assert all(r.signal_strength == 0.9 for r in records)
    assert all(r.context_summary for r in records)
    assert all(r.deterministic_id.startswith('backfill_xero_') for r in records)
    # All but the last should have an outcome (paired with the next month).
    with_outcome = [r for r in records if r.outcome is not None]
    assert len(with_outcome) == len(records) - 1


@pytest.mark.skipif(
    not _ledger_reachable(),
    reason='Ledger DB not reachable',
)
def test_preflight_probe_reports_real_ledger_ok():
    from scripts.backfill.run import _probe_ledger_db
    failures = _probe_ledger_db()
    assert failures == [], f'unexpected preflight failures: {failures}'
