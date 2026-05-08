"""
Per-listing margin engine — eBay.

Twin of ``core/etsy_intel/margin/per_sku.py`` so Manufacture's
"All channels (combined)" view iterates one schema across Amazon /
Etsy / eBay. Aggregation key: ``item_id`` (eBay's listing primary
key); response field is named ``asin`` for frontend MarginRow
compatibility, same convention as the Etsy engine.

Sources joined per listing:

  1. ``ebay_sales``        — gross revenue + units over the lookback
  2. eBay rate card v1 OR
     API-derived per-line fees from ``ebay_sales.fees`` when present
  3. Manufacture COGS      — ``/api/costs/price/bulk/?marketplace=``
                             (empty marketplace = default UK warehouse;
                             same fulfilment as Etsy and Amazon UK)
  4. ``ebay_ad_spend``     — Promoted Listings spend, prorated to the
                             lookback window via the same daterange
                             overlap pattern as Etsy ad-spend.

VAT
---
NBNE is UK VAT-registered. eBay's `total_paid` is gross of VAT for
UK→UK orders (seller remits to HMRC); for non-UK orders eBay
collects/remits in jurisdictions where it's required and the seller
payout is already net.

``ebay_sales.buyer_country`` is captured per-row (PII-safe ISO code).
v1 logic per the brief decision:

    UK buyer    → net = total_paid / 1.20
    non-UK      → net = total_paid (already net)
    NULL/missing → treat as net (no divisor) — safer default than
                   "default UK" since over-correcting is worse than
                   under-correcting in the loss-maker analysis context

Fee model
---------
eBay returns per-line fees in `pricingSummary.fee.value` *sometimes*.
When present we use it (``fee_source='ebay_api_v1'``); when missing,
fall back to a rate-card calc:

    fees ≈ total_paid * 12.8% + (£0.30 per ORDER)
    fee_source = 'ebay_rate_card_v1'

The £0.30 is per order, not per line. Allocated proportionally to
line value: ``line_share = line_total / order_total × £0.30``. Done
in SQL during the per-line aggregate.

Confidence
----------
HIGH   — cost_source='override' AND m_number resolved AND fee_source='ebay_api_v1'
MEDIUM — exactly one missing
LOW    — two or more missing
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from core.amazon_intel.manufacture_client import get_costs_bulk
from core.ebay_intel.db import get_conn


logger = logging.getLogger(__name__)


ZERO = Decimal('0')
TWO_PLACES = Decimal('0.01')

UK_VAT_RATE = Decimal('0.20')

# eBay UK rate card v1 (verified 2026-05-08 from eBay seller fees page).
# Used as fallback when per-line API fees are missing.
EBAY_FVF_RATE         = Decimal('0.128')   # 12.8% of total_paid
EBAY_FIXED_FEE_PER_ORDER = Decimal('0.30')  # £0.30 per ORDER (allocated by line value)


@dataclass
class EbayMargin:
    """Field-for-field twin of EtsyMargin and SkuMargin so Manufacture's
    MarginRow type accepts all three."""
    asin: str                                  # eBay item_id as string
    marketplace: str                           # always 'EBAY'
    m_number: Optional[str]
    units: int
    gross_revenue: Decimal
    net_revenue: Decimal
    fees_per_unit: Optional[Decimal]
    fees_total: Optional[Decimal]
    cogs_per_unit: Optional[Decimal]
    cogs_total: Optional[Decimal]
    ad_spend: Decimal
    gross_profit: Optional[Decimal]
    gross_margin_pct: Optional[Decimal]
    net_profit: Optional[Decimal]
    net_margin_pct: Optional[Decimal]
    blank_raw: Optional[str]
    blank_normalized: Optional[str]
    fee_source: str                            # 'ebay_api_v1' | 'ebay_rate_card_v1' | 'mixed'
    cost_source: str
    is_composite: bool
    confidence: str


def _pct(numer: Decimal, denom: Decimal) -> Optional[Decimal]:
    if denom is None or denom == 0:
        return None
    return (Decimal('100') * numer / denom).quantize(TWO_PLACES)


def _confidence(cost_source: str, m_number: Optional[str], fee_source: str) -> str:
    has_override = cost_source == 'override'
    has_m = bool(m_number)
    has_api_fees = fee_source == 'ebay_api_v1'
    score = sum([has_override, has_m, has_api_fees])
    if score == 3:
        return 'HIGH'
    if score == 2:
        return 'MEDIUM'
    return 'LOW'


def _fetch_sales_aggregate(lookback_days: int) -> dict[int, dict]:
    """
    Aggregate ebay_sales by item_id over the lookback window.

    Per-line totals + per-line API fees + per-line buyer-country share
    are summed in Python so the VAT divisor and rate-card fallback
    can be applied per-line correctly.

    Returns dict keyed by item_id with:
        units, lines, gross_total (sum of total_paid),
        api_fees_total (sum where API fee was present),
        api_fee_lines (count of lines with API fees),
        rate_card_lines (count of lines without API fees),
        order_ids: set of distinct orders contributing,
        buyer_country_units: dict[country|None, units]
    """
    sql = """
        SELECT item_id,
               order_id,
               buyer_country,
               quantity,
               total_paid,
               fees,
               total_price
          FROM ebay_sales
         WHERE item_id IS NOT NULL
           AND sale_date >= NOW() - make_interval(days => %(days)s)
    """
    out: dict[int, dict] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'days': lookback_days})
            for item_id, order_id, country, qty, total_paid, fees, total_price in cur.fetchall():
                if not item_id:
                    continue
                key = int(item_id)
                bucket = out.setdefault(key, {
                    'units': 0,
                    'lines': 0,
                    'gross_uk': ZERO,           # £ where buyer_country == 'GB'
                    'gross_non_uk': ZERO,       # £ otherwise (incl. NULL)
                    'gross_total': ZERO,
                    'api_fees_total': ZERO,
                    'api_fee_line_value': ZERO,
                    'rate_card_line_value': ZERO,
                    'rate_card_orders': set(),  # distinct orders missing API fees
                    'order_lines': [],          # for fixed-fee allocation
                })
                qty_i = int(qty or 0)
                tp = Decimal(str(total_paid or 0))
                line_total = Decimal(str(total_price or tp))

                bucket['units'] += qty_i
                bucket['lines'] += 1
                bucket['gross_total'] += tp
                # UK VAT applies only to UK shipments; eBay returns
                # 'GB' as ISO. Both null and non-UK go to non_uk
                # (treated as already-net per the brief decision).
                if (country or '').upper() == 'GB':
                    bucket['gross_uk'] += tp
                else:
                    bucket['gross_non_uk'] += tp

                if fees is not None:
                    bucket['api_fees_total'] += Decimal(str(fees))
                    bucket['api_fee_line_value'] += line_total
                else:
                    bucket['rate_card_orders'].add(order_id)
                    bucket['rate_card_line_value'] += line_total
                    bucket['order_lines'].append((order_id, line_total))
    return out


def _fetch_listing_metadata(item_ids: list[int]) -> dict[int, dict]:
    """Fetch m_number + sku + title for the given item_ids."""
    if not item_ids:
        return {}
    out: dict[int, dict] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_id, m_number, sku, title
                  FROM ebay_listings
                 WHERE item_id = ANY(%s)
                """,
                (item_ids,),
            )
            for item_id, m_number, sku, title in cur.fetchall():
                out[int(item_id)] = {
                    'm_number': m_number,
                    'sku':      sku,
                    'title':    title,
                }
    return out


def _fetch_ad_spend_prorated(
    lookback_days: int,
) -> tuple[dict[int, Decimal], set[str]]:
    """Sum prorated Promoted Listings spend per item_id over the
    lookback window. Same daterange overlap pattern as the Etsy
    ad-spend engine. Graceful degradation when the table is empty
    or unreachable.
    """
    today_d = date.today()
    lookback_start = today_d - timedelta(days=lookback_days)
    lookback_end = today_d

    sql = """
        SELECT item_id,
               SUM(
                 spend_gbp *
                 GREATEST(0,
                   (LEAST(period_end, %(lb_end)s::date)
                    - GREATEST(period_start, %(lb_start)s::date)
                    + 1)::numeric
                 ) /
                 NULLIF((period_end - period_start + 1)::numeric, 0)
               ) AS prorated_spend_gbp,
               STRING_AGG(DISTINCT source, ',') AS sources
          FROM ebay_ad_spend
         WHERE daterange(period_start, period_end + 1, '[)')
            && daterange(%(lb_start)s::date, %(lb_end)s::date + 1, '[)')
         GROUP BY item_id
    """
    out: dict[int, Decimal] = {}
    sources: set[str] = set()
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {
                    'lb_start': lookback_start,
                    'lb_end': lookback_end,
                })
                for item_id, prorated, src_csv in cur.fetchall():
                    if prorated is None:
                        continue
                    out[int(item_id)] = Decimal(str(prorated)).quantize(TWO_PLACES)
                    if src_csv:
                        for s in src_csv.split(','):
                            if s.strip():
                                sources.add(s.strip())
    except Exception as exc:
        logger.warning('ebay_ad_spend lookup failed (treating as no data): %s', exc)
    return out, sources


def _allocate_fixed_fee(order_lines: list[tuple[str, Decimal]]) -> dict[str, Decimal]:
    """Allocate £0.30 per ORDER across that order's lines, proportional
    to line value. Returns a dict mapping (order_id, line_total) tuple
    to the line's share of the £0.30.

    For per-listing aggregation, we sum the shares of all lines for
    each item_id afterwards. Done as a separate function so the math
    is testable and obvious.
    """
    by_order: dict[str, Decimal] = {}
    for order_id, line_total in order_lines:
        by_order[order_id] = by_order.get(order_id, ZERO) + line_total
    return by_order  # caller uses this to compute share-per-line


async def compute_margins(
    lookback_days: int = 30,
) -> tuple[list[EbayMargin], dict]:
    """Per-listing margin breakdown for eBay. One row per item_id.

    Returns (margins, ad_meta) where ad_meta = {
        'has_ad_data': bool,
        'ad_sources':  list[str],
    }
    """
    sales = _fetch_sales_aggregate(lookback_days)
    if not sales:
        return [], {'has_ad_data': False, 'ad_sources': []}

    listing_meta = _fetch_listing_metadata(list(sales.keys()))
    ad_spend_by_listing, ad_sources = _fetch_ad_spend_prorated(lookback_days)

    m_numbers = sorted({
        m['m_number'] for m in listing_meta.values() if m.get('m_number')
    })
    costs, _overhead_ctx = (
        await get_costs_bulk(m_numbers, marketplace='')
        if m_numbers else ({}, {})
    )

    results: list[EbayMargin] = []
    for item_id, agg in sales.items():
        units = agg['units']

        # Net revenue: UK portion divides by 1.20, non-UK passes through
        net_uk = (agg['gross_uk'] / (Decimal('1') + UK_VAT_RATE)).quantize(TWO_PLACES)
        net_non_uk = agg['gross_non_uk'].quantize(TWO_PLACES)
        net = net_uk + net_non_uk

        # Fees: API where present + rate-card for the rest
        api_fees = agg['api_fees_total'].quantize(TWO_PLACES)

        # Rate-card share for lines without API fees
        rate_card_total = ZERO
        if agg['rate_card_line_value'] > 0:
            # FVF on the rate-card-fallback line value
            rate_card_total = (
                agg['rate_card_line_value'] * EBAY_FVF_RATE
            )
            # Plus this listing's share of the £0.30/order across the
            # orders contributing rate-card lines. Allocate to this
            # listing proportional to its share of each order's value.
            order_totals = _allocate_fixed_fee(agg['order_lines'])
            for order_id, line_value in agg['order_lines']:
                order_total = order_totals.get(order_id, ZERO)
                if order_total > 0:
                    rate_card_total += (
                        EBAY_FIXED_FEE_PER_ORDER * (line_value / order_total)
                    )

        # Fees are gross of UK VAT in the eBay billing — divide for
        # parity with the Amazon/Etsy convention where fees are
        # reported ex-VAT. Same caveat as the revenue side: only the
        # UK portion gets divided.
        gross_fees = (api_fees + rate_card_total)
        # Approximate UK share of fees by the UK share of revenue
        if agg['gross_total'] > 0:
            uk_share = agg['gross_uk'] / agg['gross_total']
        else:
            uk_share = Decimal('0')
        fees_uk = gross_fees * uk_share
        fees_non_uk = gross_fees * (Decimal('1') - uk_share)
        fees_total = (
            (fees_uk / (Decimal('1') + UK_VAT_RATE)) + fees_non_uk
        ).quantize(TWO_PLACES)
        fees_per_unit = (fees_total / units).quantize(TWO_PLACES) if units else None

        # Determine fee_source — 'ebay_api_v1' if EVERY line had API
        # fees, 'ebay_rate_card_v1' if NONE did, 'mixed' if both.
        if api_fees > 0 and rate_card_total > 0:
            fee_source = 'mixed'
        elif rate_card_total > 0:
            fee_source = 'ebay_rate_card_v1'
        else:
            fee_source = 'ebay_api_v1'

        # COGS
        meta = listing_meta.get(item_id, {})
        m_number = meta.get('m_number')
        cost_row = costs.get(m_number) if m_number else None
        cost_source = 'missing'
        is_composite = False
        blank_raw = None
        blank_normalized = None
        cogs_per_unit: Optional[Decimal] = None
        cogs_total: Optional[Decimal] = None
        if cost_row and cost_row.get('cost_gbp') is not None:
            cogs_per_unit = Decimal(str(cost_row['cost_gbp'])).quantize(TWO_PLACES)
            cogs_total = (cogs_per_unit * units).quantize(TWO_PLACES)
            cost_source = cost_row.get('source') or 'engine'
            is_composite = bool(cost_row.get('is_composite'))
            blank_raw = cost_row.get('blank_raw')
            blank_normalized = cost_row.get('blank_normalized')

        ad_spend = ad_spend_by_listing.get(item_id, ZERO)

        if cogs_total is not None:
            gross_profit = (net - fees_total - cogs_total).quantize(TWO_PLACES)
            net_profit = (gross_profit - ad_spend).quantize(TWO_PLACES)
            gross_margin_pct = _pct(gross_profit, net)
            net_margin_pct = _pct(net_profit, net)
        else:
            gross_profit = None
            net_profit = None
            gross_margin_pct = None
            net_margin_pct = None

        results.append(EbayMargin(
            asin=str(item_id),
            marketplace='EBAY',
            m_number=m_number,
            units=units,
            gross_revenue=agg['gross_total'].quantize(TWO_PLACES),
            net_revenue=net,
            fees_per_unit=fees_per_unit,
            fees_total=fees_total,
            cogs_per_unit=cogs_per_unit,
            cogs_total=cogs_total,
            ad_spend=ad_spend.quantize(TWO_PLACES),
            gross_profit=gross_profit,
            gross_margin_pct=gross_margin_pct,
            net_profit=net_profit,
            net_margin_pct=net_margin_pct,
            blank_raw=blank_raw,
            blank_normalized=blank_normalized,
            fee_source=fee_source,
            cost_source=cost_source,
            is_composite=is_composite,
            confidence=_confidence(cost_source, m_number, fee_source),
        ))

    has_ad_data = any(m.ad_spend > 0 for m in results)
    ad_meta = {
        'has_ad_data': has_ad_data,
        'ad_sources': sorted(ad_sources) if has_ad_data else [],
    }
    return results, ad_meta


def margin_to_dict(m: EbayMargin) -> dict:
    d = asdict(m)
    for k, v in list(d.items()):
        if isinstance(v, Decimal):
            d[k] = float(v)
    return d


def bucket_margins(margins: list[EbayMargin]) -> dict:
    """Field-for-field twin of the Etsy/Amazon bucket_margins, including
    total_loss_bleed + top_loss_makers."""
    scored = [m for m in margins if m.net_margin_pct is not None]
    all_net_rev = round(sum((float(m.net_revenue) for m in margins), 0.0), 2)
    if not scored:
        return {
            'total_skus': len(margins),
            'scored_skus': 0,
            'buckets': {'healthy': 0, 'thin': 0, 'unprofitable': 0,
                        'unknown': len(margins)},
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
    total_net_rev = sum((float(m.net_revenue) for m in margins), 0.0)
    total_net_profit = sum((float(m.net_profit or 0) for m in scored), 0.0)
    losers = [m for m in scored if (m.net_profit or 0) < 0]
    total_loss_bleed = round(
        sum(float(m.net_profit or 0) for m in losers), 2,
    )
    top_losers = sorted(losers, key=lambda x: float(x.net_profit or 0))[:5]
    top_loss_makers = [
        {
            'asin':           m.asin,
            'm_number':       m.m_number,
            'marketplace':    m.marketplace,
            'units':          m.units,
            'net_revenue':    float(m.net_revenue),
            'net_profit':     float(m.net_profit or 0),
            'net_margin_pct': float(m.net_margin_pct or 0),
            'confidence':     m.confidence,
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
