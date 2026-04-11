"""
Source 1 — xero.

Reconstructs monthly P&L decisions from the NBNE Ledger database
(``D:/ledger``). Each month is ONE decision: "continue current
channel mix and pricing posture this month". The outcome is the
next month's margin delta — positive = the posture was validated,
negative = a warning sign.

The data lives in the Ledger project's Postgres. By default we
connect via ``LEDGER_DATABASE_URL``, falling back to the local
Docker container at ``postgresql://postgres:postgres123@localhost:5432/ledger``
if that env var is not set. The LAN cairn DB is a separate
instance — do not point this source at ``DATABASE_URL``.

Signal strength 0.9 (structured numbers, not narrative inference).

Lesson gate: the pipeline only calls Sonnet for months where the
month-over-month margin moved by more than 10 percentage points.
Routine months add retrieval value through similarity search
without a per-month lesson.

YAML / hand-input: none. This source is fully automatic.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import psycopg2

from .base import HistoricalSource, RawHistoricalRecord, RawOutcome


log = logging.getLogger(__name__)


DEFAULT_LEDGER_URL = 'postgresql://postgres:postgres123@localhost:5432/ledger'


class XeroSource:
    """Monthly P&L decision reconstruction from the Ledger DB."""

    name: str = 'xero'
    source_type: str = 'xero'

    def __init__(
        self,
        db_url: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ):
        self.db_url = db_url or os.getenv('LEDGER_DATABASE_URL') or DEFAULT_LEDGER_URL
        self.start_date = start_date
        self.end_date = end_date

    # ── Iteration ───────────────────────────────────────────────────────

    def iter_records(self) -> Iterator[RawHistoricalRecord]:
        try:
            conn = psycopg2.connect(self.db_url, connect_timeout=5)
        except Exception as exc:
            raise RuntimeError(
                f'xero source: could not connect to Ledger DB at {self.db_url}: {exc}'
            )
        try:
            months = self._fetch_monthly(conn)
            if not months:
                return
            # months is an ordered list of MonthlyPL dataclasses,
            # oldest first, so we can pair month N with month N+1
            # to compute the margin delta for the outcome.
            for i, month in enumerate(months):
                next_month = months[i + 1] if i + 1 < len(months) else None
                yield _build_record(month, next_month)
        finally:
            conn.close()

    def _fetch_monthly(self, conn) -> list['MonthlyPL']:
        """Pull one row per calendar month, across the requested window."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    date_trunc('month', date) AS month,
                    COUNT(*) AS tx_count,
                    COALESCE(SUM(gross_revenue), 0)::numeric AS gross,
                    COALESCE(SUM(net_revenue_gbp), 0)::numeric AS net,
                    COALESCE(SUM(channel_fees), 0)::numeric AS fees,
                    COALESCE(SUM(ad_fees), 0)::numeric AS ads,
                    COALESCE(SUM(postage_cost), 0)::numeric AS postage
                FROM revenue_transactions
                WHERE (%s::date IS NULL OR date >= %s::date)
                  AND (%s::date IS NULL OR date <= %s::date)
                GROUP BY 1
                ORDER BY 1
                """,
                (
                    self.start_date.date() if self.start_date else None,
                    self.start_date.date() if self.start_date else None,
                    self.end_date.date() if self.end_date else None,
                    self.end_date.date() if self.end_date else None,
                ),
            )
            rev_rows = cur.fetchall()

            cur.execute(
                """
                SELECT
                    date_trunc('month', date) AS month,
                    COALESCE(SUM(amount_gbp), 0)::numeric AS expenditure
                FROM expenditure
                WHERE (%s::date IS NULL OR date >= %s::date)
                  AND (%s::date IS NULL OR date <= %s::date)
                GROUP BY 1
                ORDER BY 1
                """,
                (
                    self.start_date.date() if self.start_date else None,
                    self.start_date.date() if self.start_date else None,
                    self.end_date.date() if self.end_date else None,
                    self.end_date.date() if self.end_date else None,
                ),
            )
            exp_rows = dict(cur.fetchall())

            # Top 3 channels per month by net revenue.
            cur.execute(
                """
                SELECT
                    date_trunc('month', date) AS month,
                    channel,
                    COALESCE(SUM(net_revenue_gbp), 0)::numeric AS net
                FROM revenue_transactions
                WHERE (%s::date IS NULL OR date >= %s::date)
                  AND (%s::date IS NULL OR date <= %s::date)
                GROUP BY 1, 2
                """,
                (
                    self.start_date.date() if self.start_date else None,
                    self.start_date.date() if self.start_date else None,
                    self.end_date.date() if self.end_date else None,
                    self.end_date.date() if self.end_date else None,
                ),
            )
            channel_map: dict[Any, list[tuple[str, Decimal]]] = {}
            for month, channel, net in cur.fetchall():
                channel_map.setdefault(month, []).append((channel, net))

        months: list[MonthlyPL] = []
        for month_dt, tx_count, gross, net, fees, ads, postage in rev_rows:
            expenditure = exp_rows.get(month_dt, Decimal(0))
            top_channels = sorted(
                channel_map.get(month_dt, []),
                key=lambda kv: kv[1],
                reverse=True,
            )[:3]
            months.append(MonthlyPL(
                month=_ensure_utc(month_dt),
                tx_count=int(tx_count),
                gross_revenue=Decimal(gross),
                net_revenue=Decimal(net),
                channel_fees=Decimal(fees),
                ad_fees=Decimal(ads),
                postage_cost=Decimal(postage),
                expenditure=Decimal(expenditure),
                top_channels=top_channels,
            ))
        return months


# ── Dataclass for monthly P&L ──────────────────────────────────────────


from dataclasses import dataclass, field


@dataclass
class MonthlyPL:
    month: datetime
    tx_count: int
    gross_revenue: Decimal
    net_revenue: Decimal
    channel_fees: Decimal
    ad_fees: Decimal
    postage_cost: Decimal
    expenditure: Decimal
    top_channels: list[tuple[str, Decimal]] = field(default_factory=list)

    @property
    def gross_margin(self) -> float:
        """Net revenue as a fraction of gross revenue.

        This measures how much of gross survives channel fees, ads,
        and postage — the operational margin e-commerce businesses
        actually live or die by. We deliberately do NOT subtract
        ``expenditure`` here because the Ledger's expenditure table
        is a sparse overhead ledger, not a full COGS ledger — using
        it produced wildly inflated "margins" (e.g. March 2025
        appeared at 99.97% because only £75 of overheads landed in
        the expenditure table that month).

        Expenditure is still surfaced in ``context_summary`` and
        ``raw_source_ref`` so downstream analysis (lessons, retrieval)
        can see the overhead figure separately.
        """
        gross = float(self.gross_revenue)
        if gross == 0:
            return 0.0
        return float(self.net_revenue) / gross


# ── Record builder ─────────────────────────────────────────────────────


def _build_record(
    month: MonthlyPL,
    next_month: MonthlyPL | None,
) -> RawHistoricalRecord:
    month_label = month.month.strftime('%Y-%m')
    deterministic_id = f"backfill_xero_{month_label.replace('-', '_')}"

    top3_txt = ', '.join(
        f'{ch} £{float(net):,.0f}' for ch, net in month.top_channels
    ) if month.top_channels else '(no channel data)'

    margin_pct = month.gross_margin * 100
    context_summary = (
        f"In {month_label}, NBNE posted £{float(month.gross_revenue):,.0f} "
        f"gross revenue across {month.tx_count} transactions, net "
        f"£{float(month.net_revenue):,.0f} after channel fees "
        f"(£{float(month.channel_fees):,.0f}), ads "
        f"(£{float(month.ad_fees):,.0f}) and postage "
        f"(£{float(month.postage_cost):,.0f}) — a net/gross ratio of "
        f"{margin_pct:.1f}%. Overheads booked to the expenditure ledger "
        f"this month: £{float(month.expenditure):,.0f}. "
        f"Top channels: {top3_txt}."
    )

    chosen_path = (
        f'Continued current channel mix and pricing posture in {month_label} '
        f'without a material change — {top3_txt}.'
    )

    outcome: RawOutcome | None = None
    margin_delta_pp: float | None = None
    if next_month is not None:
        next_margin_pct = next_month.gross_margin * 100
        margin_delta_pp = next_margin_pct - margin_pct
        outcome_sign = '+' if margin_delta_pp >= 0 else ''
        next_label = next_month.month.strftime('%Y-%m')
        outcome_text = (
            f'In {next_label} (the month following), gross margin moved '
            f'{outcome_sign}{margin_delta_pp:.1f} percentage points to '
            f'{next_margin_pct:.1f}% on £{float(next_month.net_revenue):,.0f} '
            'net revenue.'
        )
        # chosen_path_score: bound to [-1, 1] by scaling the delta.
        # Scale factor 15 is chosen so the pipeline's
        # should_generate_lesson gate (|score| >= 0.7) fires on
        # months with |delta_pp| >= 10.5 — matching the brief's
        # "only months with |margin_delta| > 10%" rule.
        score = max(-1.0, min(1.0, margin_delta_pp / 15.0))
        outcome = RawOutcome(
            observed_at=next_month.month,
            actual_result=outcome_text,
            chosen_path_score=score,
            metrics={
                'month': month_label,
                'gross_revenue_gbp': float(month.gross_revenue),
                'net_revenue_gbp': float(month.net_revenue),
                'expenditure_gbp': float(month.expenditure),
                'margin_pct': margin_pct,
                'next_margin_pct': next_margin_pct,
                'margin_delta_pp': margin_delta_pp,
            },
        )

    raw_source_ref = {
        'month': month_label,
        'tx_count': month.tx_count,
        'top_channels': [
            {'channel': ch, 'net_gbp': float(net)}
            for ch, net in month.top_channels
        ],
    }

    return RawHistoricalRecord(
        deterministic_id=deterministic_id,
        source_type='xero',
        decided_at=month.month,
        chosen_path=chosen_path,
        context_summary=context_summary,
        archetype_tags=None,  # Haiku picks from the context summary
        rejected_paths=None,  # No explicit alternatives tracked here
        signal_strength=0.9,
        case_id=None,
        raw_source_ref=raw_source_ref,
        needs_privacy_scrub=False,
        needs_privacy_review=False,
        outcome=outcome,
        verbatim_lesson=None,  # Gate path — Sonnet iff |delta| > 10pp
    )


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
