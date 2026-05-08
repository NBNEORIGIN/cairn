"""
Per-SKU margin engine.

Joins four sources into a single per-(asin, marketplace) margin breakdown:

  1. ami_orders                     — gross revenue, units, over lookback
  2. ami_fee_snapshots              — referral + FBA + other fees per unit
  3. Manufacture /api/costs/price/… — material + labour + overhead per unit
  4. ami_advertising_data           — ad spend allocated per ASIN (optional)

Revenue is converted to net using marketplace VAT rate (see ..vat).

Output (per SKU):
    net_revenue, units, gross_revenue, fees, cogs, ad_spend,
    gross_profit, gross_margin_pct, net_profit, net_margin_pct,
    confidence (HIGH | MEDIUM | LOW)

Confidence rules:
    HIGH    — fees present (Success status) AND cost source == 'override'
    MEDIUM  — fees present AND cost source == 'blank' non-composite
    LOW     — anything else (missing fees, fallback cost, composite blank)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Optional

from ..db import get_conn
from ..fx import convert_to_gbp, marketplace_currency
from ..manufacture_client import get_costs_bulk
from ..vat import net_revenue
from .quartile_brief import MARKETPLACE_ALIASES

logger = logging.getLogger(__name__)


ZERO = Decimal('0')
TWO_PLACES = Decimal('0.01')


@dataclass
class SkuMargin:
    asin: str
    marketplace: str
    m_number: Optional[str]
    units: int
    gross_revenue: Decimal
    net_revenue: Decimal
    fees_per_unit: Optional[Decimal]
    fees_total: Optional[Decimal]
    cogs_per_unit: Optional[Decimal]
    cogs_total: Optional[Decimal]
    ad_spend: Decimal
    gross_profit: Optional[Decimal]            # net_revenue - fees - cogs
    gross_margin_pct: Optional[Decimal]        # gross_profit / net_revenue
    net_profit: Optional[Decimal]              # gross_profit - ad_spend
    net_margin_pct: Optional[Decimal]          # net_profit / net_revenue
    blank_raw: Optional[str]
    blank_normalized: Optional[str]
    fee_source: str                            # 'snapshot' | 'missing'
    cost_source: str                           # 'override' | 'blank' | 'fallback' | 'missing'
    is_composite: bool
    confidence: str                            # HIGH | MEDIUM | LOW


def _marketplace_aliases(marketplace: str) -> list[str]:
    return MARKETPLACE_ALIASES.get(marketplace.upper(), [marketplace.upper()])


def _fetch_orders_aggregate(
    marketplace: str,
    lookback_days: int,
) -> dict[tuple[str, str], dict]:
    """
    Aggregate orders by (asin, marketplace). Marketplace alias logic handles
    the UK↔GB mismatch between ami_orders.marketplace and the rest of the system.
    Returns dict keyed by (asin, canonical_marketplace).
    """
    aliases = _marketplace_aliases(marketplace)
    canonical = marketplace.upper()
    sql = """
        SELECT asin,
               COUNT(*)                          AS order_line_count,
               SUM(quantity)                     AS units,
               SUM(item_price_amount)            AS gross_revenue,
               MIN(m_number)                     AS m_number
          FROM ami_orders
         WHERE asin IS NOT NULL AND asin <> ''
           AND marketplace = ANY(%(mp)s)
           AND order_date >= CURRENT_DATE - make_interval(days => %(days)s)
         GROUP BY asin
    """
    out: dict[tuple[str, str], dict] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'mp': aliases, 'days': lookback_days})
            for asin, _lines, units, gross, m_number in cur.fetchall():
                if not units or not gross:
                    continue
                out[(asin, canonical)] = {
                    'units': int(units),
                    'gross_revenue': Decimal(str(gross)),
                    'm_number': m_number,
                }
    return out


def _fetch_fee_snapshots(
    marketplace: str,
) -> dict[str, dict]:
    sql = """
        SELECT asin, total_fees, referral_fee, fba_fee, variable_closing_fee,
               other_fees, api_status, price_point_amount
          FROM ami_fee_snapshots
         WHERE marketplace = %s
    """
    out: dict[str, dict] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (marketplace.upper(),))
            for r in cur.fetchall():
                asin = r[0]
                out[asin] = {
                    'total_fees': r[1],
                    'referral_fee': r[2],
                    'fba_fee': r[3],
                    'variable_closing_fee': r[4],
                    'other_fees': r[5],
                    'api_status': r[6],
                    'price_point': r[7],
                }
    return out


def _fetch_ad_spend(
    marketplace: str,
    lookback_days: int,
) -> dict[str, Decimal]:
    """Ad spend per ASIN over the lookback window."""
    sql = """
        SELECT d.asin, SUM(d.spend) AS spend
          FROM ami_advertising_data d
          LEFT JOIN ami_advertising_profiles p ON p.profile_id = d.profile_id
         WHERE d.asin IS NOT NULL AND d.asin <> ''
           AND d.report_date IS NOT NULL
           AND d.report_date >= CURRENT_DATE - make_interval(days => %(days)s)
           AND p.country_code = %(mkt)s
         GROUP BY d.asin
    """
    out: dict[str, Decimal] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'mkt': marketplace.upper(), 'days': lookback_days})
            for asin, spend in cur.fetchall():
                out[asin] = Decimal(str(spend or 0))
    return out


def _pct(numer: Decimal, denom: Decimal) -> Optional[Decimal]:
    if denom is None or denom == 0:
        return None
    return (Decimal('100') * numer / denom).quantize(TWO_PLACES)


def _confidence(fee_source: str, cost_source: str, is_composite: bool) -> str:
    if fee_source != 'snapshot':
        return 'LOW'
    if cost_source == 'override':
        return 'HIGH'
    if cost_source == 'blank' and not is_composite:
        return 'MEDIUM'
    return 'LOW'


def _fetch_channel_revenue_summary(lookback_days: int = 30) -> dict[str, Decimal]:
    """
    Aggregate net revenue across all channels for overhead allocation.
    Returns dict with keys: 'amazon_total', 'etsy', per-marketplace totals.
    All values in GBP — Amazon marketplaces converted via VAT rate AND
    FX (the docstring used to claim GBP-uniform but only VAT was applied,
    silently leaving USD/EUR/CAD/AUD mixed in. Fixed 2026-05-08).
    """
    from ..vat import net_revenue as nr
    from ..fx import convert_to_gbp, marketplace_currency

    out: dict[str, Decimal] = {}

    # Amazon — all marketplaces
    sql = """
        SELECT marketplace, SUM(item_price_amount) AS gross
        FROM ami_orders
        WHERE asin IS NOT NULL AND asin <> ''
          AND order_date >= CURRENT_DATE - make_interval(days => %(days)s)
        GROUP BY marketplace
    """
    amazon_total = ZERO
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'days': lookback_days})
            for mkt, gross in cur.fetchall():
                if gross:
                    gross_gbp = convert_to_gbp(
                        Decimal(str(gross)), marketplace_currency(mkt),
                    )
                    net = nr(gross_gbp, mkt)
                    out[f'amazon_{mkt}'] = net
                    amazon_total += net
    out['amazon_total'] = amazon_total

    # Etsy
    try:
        sql_etsy = """
            SELECT COALESCE(SUM(price * quantity), 0)
            FROM etsy_sales
            WHERE sale_date >= CURRENT_DATE - make_interval(days => %(days)s)
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_etsy, {'days': lookback_days})
                etsy_gross = cur.fetchone()[0] or 0
                out['etsy'] = Decimal(str(etsy_gross)).quantize(TWO_PLACES)
    except Exception:
        out['etsy'] = ZERO

    return out


async def compute_margins(
    marketplace: str,
    lookback_days: int = 30,
) -> list[SkuMargin]:
    """
    Compute per-SKU margins for a marketplace over the lookback window.
    Returns one SkuMargin per distinct ASIN with orders.

    Overhead allocation: instead of flat per-unit overhead, allocates
    monthly overhead proportional to each channel's share of total revenue.
    """
    orders = _fetch_orders_aggregate(marketplace, lookback_days)
    if not orders:
        return []

    fees = _fetch_fee_snapshots(marketplace)
    ads = _fetch_ad_spend(marketplace, lookback_days)

    m_numbers = sorted({v['m_number'] for v in orders.values() if v.get('m_number')})
    # Thread the marketplace param so Manufacture's MNumberCostOverride
    # can return per-marketplace COGS (UK override beats default, etc).
    # Added 2026-05-08 — additive on the Manufacture side, no schema
    # change here. Falls back to default + cost engine when no override
    # exists for this marketplace. The .upper() normalisation matches
    # what /margin/per-sku already does for its own canonical handling.
    costs, overhead_ctx = (
        await get_costs_bulk(m_numbers, marketplace=marketplace.upper())
        if m_numbers else ({}, {})
    )

    # Channel-weighted overhead calculation
    channel_rev = _fetch_channel_revenue_summary(lookback_days)
    monthly_overhead = Decimal(str(overhead_ctx.get('monthly_overhead_gbp', 24500)))
    b2b_rev = Decimal(str(overhead_ctx.get('b2b_monthly_revenue_gbp', 0)))
    ebay_rev = Decimal(str(overhead_ctx.get('ebay_monthly_revenue_gbp', 0)))
    flat_overhead = Decimal(str(overhead_ctx.get('overhead_per_unit_gbp', '6.45')))

    # Scale monthly figures to match the lookback window
    scale = Decimal(str(lookback_days)) / Decimal('30')
    scaled_overhead = (monthly_overhead * scale).quantize(TWO_PLACES)
    scaled_b2b = (b2b_rev * scale).quantize(TWO_PLACES)
    scaled_ebay = (ebay_rev * scale).quantize(TWO_PLACES)

    # Total revenue across ALL channels in the lookback window
    total_rev = (
        channel_rev.get('amazon_total', ZERO)
        + channel_rev.get('etsy', ZERO)
        + scaled_ebay
        + scaled_b2b
    )

    # This marketplace's revenue + units
    canonical = marketplace.upper()
    aliases = _marketplace_aliases(marketplace)
    mkt_rev = ZERO
    for alias in aliases:
        mkt_rev += channel_rev.get(f'amazon_{alias}', ZERO)

    # Total units for this marketplace
    mkt_units = sum(agg['units'] for agg in orders.values())

    # Per-unit overhead for this marketplace
    if total_rev > 0 and mkt_units > 0:
        mkt_overhead_share = (mkt_rev / total_rev) if total_rev > 0 else ZERO
        mkt_overhead_total = (scaled_overhead * mkt_overhead_share).quantize(TWO_PLACES)
        overhead_per_unit = (mkt_overhead_total / mkt_units).quantize(TWO_PLACES)
    else:
        overhead_per_unit = flat_overhead  # fallback to flat rate

    logger.info(
        "Overhead allocation for %s: rev=%.0f (%.1f%% of %.0f total), "
        "%d units, £%.2f/unit (flat was £%.2f)",
        canonical, mkt_rev, (float(mkt_rev / total_rev * 100) if total_rev else 0),
        total_rev, mkt_units, overhead_per_unit, flat_overhead,
    )

    # ── Currency normalisation ──────────────────────────────────────────
    # Everything in this function operates in GBP from this point on.
    # ami_orders revenue, ami_fee_snapshots fees, and ami_advertising_data
    # spend are all in marketplace-native currency (USD/EUR/CAD/AUD).
    # Manufacture's COGS is already GBP. Mixing the two over-states
    # non-UK profit by 25-50% — fixed 2026-05-08 by converting native
    # values to GBP at the row level using a daily FX snapshot
    # (ami_fx_rates). UK passes through at rate=1.0 so its numbers are
    # byte-identical to the pre-FX behaviour.
    native_currency = marketplace_currency(canonical)

    results: list[SkuMargin] = []
    for (asin, mkt), agg in orders.items():
        units = agg['units']
        # Convert revenue native → GBP up front; net_revenue (VAT) is then
        # applied to the GBP amount. The VAT rate logic doesn't care about
        # currency — it's a multiplicative percentage off gross.
        gross_native = agg['gross_revenue']
        gross = convert_to_gbp(gross_native, native_currency)
        net = net_revenue(gross, mkt)
        m_number = agg.get('m_number')

        fee_row = fees.get(asin)
        if fee_row and fee_row.get('total_fees') is not None and fee_row.get('api_status') == 'Success':
            # Fees from getMyFeesEstimate are in the marketplace currency
            # too — convert to GBP at the same rate so subtraction is
            # currency-consistent.
            fees_per_unit_native = Decimal(str(fee_row['total_fees']))
            fees_per_unit = convert_to_gbp(fees_per_unit_native, native_currency)
            fees_total = (fees_per_unit * units).quantize(TWO_PLACES)
            fees_per_unit = fees_per_unit.quantize(TWO_PLACES)
            fee_source = 'snapshot'
        else:
            fees_per_unit = None
            fees_total = None
            fee_source = 'missing'

        cost_row = costs.get(m_number) if m_number else None
        if cost_row and cost_row.get('cost_gbp') is not None:
            # Use material + labour from Manufacture, replace overhead with channel-weighted
            material = Decimal(str(cost_row.get('material_gbp') or 0))
            labour = Decimal(str(cost_row.get('labour_gbp') or 0))
            # For overrides (source='override'), cost_gbp is all-in — use as-is
            if cost_row.get('source') == 'override':
                cogs_per_unit = Decimal(str(cost_row['cost_gbp']))
            else:
                cogs_per_unit = (material + labour + overhead_per_unit).quantize(TWO_PLACES)
            cogs_total = (cogs_per_unit * units).quantize(TWO_PLACES)
            cost_source = cost_row.get('source') or 'missing'
            is_composite = bool(cost_row.get('is_composite'))
            blank_raw = cost_row.get('blank_raw')
            blank_normalized = cost_row.get('blank_normalized')
        else:
            cogs_per_unit = None
            cogs_total = None
            cost_source = 'missing'
            is_composite = False
            blank_raw = None
            blank_normalized = None

        # Ad spend native → GBP. Amazon Ads reports spend in marketplace
        # currency; this is the third leg of the conversion.
        ad_spend_native = ads.get(asin, ZERO)
        ad_spend = convert_to_gbp(ad_spend_native, native_currency).quantize(TWO_PLACES)

        if fees_total is not None and cogs_total is not None:
            gross_profit = (net - fees_total - cogs_total).quantize(TWO_PLACES)
            net_profit = (gross_profit - ad_spend).quantize(TWO_PLACES)
            gross_margin_pct = _pct(gross_profit, net)
            net_margin_pct = _pct(net_profit, net)
        else:
            gross_profit = None
            net_profit = None
            gross_margin_pct = None
            net_margin_pct = None

        results.append(SkuMargin(
            asin=asin,
            marketplace=mkt,
            m_number=m_number,
            units=units,
            gross_revenue=gross.quantize(TWO_PLACES),
            net_revenue=net,
            fees_per_unit=fees_per_unit,
            fees_total=fees_total,
            cogs_per_unit=cogs_per_unit,
            cogs_total=cogs_total,
            ad_spend=ad_spend,
            gross_profit=gross_profit,
            gross_margin_pct=gross_margin_pct,
            net_profit=net_profit,
            net_margin_pct=net_margin_pct,
            blank_raw=blank_raw,
            blank_normalized=blank_normalized,
            fee_source=fee_source,
            cost_source=cost_source,
            is_composite=is_composite,
            confidence=_confidence(fee_source, cost_source, is_composite),
        ))
    return results


def margin_to_dict(m: SkuMargin) -> dict:
    """JSON-safe dict — decimals → floats."""
    d = asdict(m)
    for k, v in list(d.items()):
        if isinstance(v, Decimal):
            d[k] = float(v)
    return d


def bucket_margins(margins: list[SkuMargin]) -> dict:
    """
    Summary buckets for the top-line margin panel. Uses net_margin_pct
    quartiles, but drops SKUs without a computed margin.

    The summary also surfaces loss-makers directly so a consumer can
    answer "what's bleeding cash?" without iterating the full results
    list. Toby's framing 2026-05-08: the per-SKU endpoints exist to
    spot loss-making vs profitable products; the summary now makes
    that visible at the top-line level alongside the bucket counts.
    """
    scored = [m for m in margins if m.net_margin_pct is not None]
    all_net_rev = round(sum((float(m.net_revenue) for m in margins), 0.0), 2)
    if not scored:
        return {
            'total_skus': len(margins),
            'scored_skus': 0,
            'buckets': {'healthy': 0, 'thin': 0, 'unprofitable': 0, 'unknown': len(margins)},
            'total_net_revenue': all_net_rev,
            'total_net_profit': 0.0,
            'total_loss_bleed': 0.0,
            'top_loss_makers': [],
        }
    healthy = thin = unprofitable = 0
    for m in scored:
        pct = float(m.net_margin_pct or 0)
        if pct >= 20:
            healthy += 1
        elif pct >= 5:
            thin += 1
        else:
            unprofitable += 1
    # Revenue includes ALL SKUs (it's a fact, not dependent on margin calc).
    # Profit only includes scored SKUs (requires COGS to compute).
    total_net_rev = sum((float(m.net_revenue) for m in margins), 0.0)
    total_net_profit = sum((float(m.net_profit or 0) for m in scored), 0.0)

    # Loss bleed — sum of negative net_profit across scored SKUs. Always
    # negative or zero. Tells you "if I retired every loss-maker I'd
    # save £X over this lookback window" (rough — assumes no spillover
    # demand; treat as upper bound of recoverable margin).
    losers = [m for m in scored if (m.net_profit or 0) < 0]
    total_loss_bleed = round(
        sum(float(m.net_profit or 0) for m in losers), 2,
    )

    # Top 5 loss-makers by absolute £ loss, surfaced in the summary so
    # the frontend can show a "biggest bleeders" panel without
    # post-processing the full results array. Each entry is a thin
    # dict — full row still in `results`.
    top_losers = sorted(losers, key=lambda x: float(x.net_profit or 0))[:5]
    top_loss_makers = [
        {
            'asin': m.asin,
            'm_number': m.m_number,
            'marketplace': m.marketplace,
            'units': m.units,
            'net_revenue': float(m.net_revenue),
            'net_profit': float(m.net_profit or 0),
            'net_margin_pct': float(m.net_margin_pct or 0),
            'confidence': m.confidence,
        }
        for m in top_losers
    ]

    return {
        'total_skus': len(margins),
        'scored_skus': len(scored),
        'buckets': {
            'healthy': healthy,
            'thin': thin,
            'unprofitable': unprofitable,
            'unknown': len(margins) - len(scored),
        },
        'total_net_revenue': round(total_net_rev, 2),
        'total_net_profit': round(total_net_profit, 2),
        'total_loss_bleed': total_loss_bleed,
        'top_loss_makers': top_loss_makers,
    }
