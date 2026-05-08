"""
Per-listing margin engine — Etsy.

Twin of ``core/amazon_intel/margin/per_sku.py`` so Manufacture's
"All channels (combined)" view can iterate one schema across both.
Aggregation key here is ``listing_id`` (Etsy's natural primary key)
not ASIN, but the response field is still named ``asin`` for the
frontend's MarginRow type.

Sources joined per SKU:

  1. ``etsy_sales``        — gross revenue + units over the lookback window
  2. Etsy rate card v1     — deterministic fee model (transaction +
                             payment processing). API-derived fees are
                             a v2 follow-up; current fees are
                             ``fee_source='etsy_rate_card_v1'`` so the
                             upgrade path is a tag swap.
  3. Manufacture COGS      — ``/api/costs/price/bulk/?marketplace=``
                             (empty marketplace = default UK warehouse,
                             which is correct for Etsy — same UK
                             facility, same DHL profile as Amazon UK).
  4. Etsy ads              — not yet ingested. ``ad_spend=0`` for v1
                             with ``off_site_ads_excluded=True`` flag
                             on the response footer to make the
                             under-statement visible.

VAT handling
------------

NBNE is UK VAT-registered. Etsy collects VAT at checkout in UK / EU
jurisdictions. The seller's payout from Etsy is gross of VAT for UK→UK
orders (seller remits to HMRC); for non-UK orders Etsy collects and
remits directly so the seller's payout is already net of VAT.

``etsy_sales.total`` doesn't currently store buyer country (the receipt
object has it but the parser drops it — flagged as a v2 follow-up).
Without per-order country, we apply a single 20% UK VAT divisor across
all sales. This:

  - is correct for UK→UK orders (the dominant share of NBNE Etsy)
  - over-corrects for non-UK orders by ~ the local VAT difference
  - matches the Amazon engine's existing convention
    (``net_revenue = gross / (1 + vat_rate)``)

Magnitude: small. NBNE Etsy is overwhelmingly UK demand; the brief
acknowledges this and accepts the simplification for v1. v2 captures
``country_iso`` from receipts and applies per-order VAT correctly.

Confidence rules (mirror Amazon)
--------------------------------

  HIGH   — cost_source == 'override' AND m_number resolved
  MEDIUM — exactly one of those missing
  LOW    — both missing OR fees couldn't be computed (rate card paths
           always work, so this is rare in practice)

Diagnosed and built 2026-05-08 alongside Manufacture's profitability
"All channels (combined)" feature.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Optional

from datetime import date, timedelta

from core.amazon_intel.manufacture_client import get_costs_bulk
from core.etsy_intel.db import get_conn


logger = logging.getLogger(__name__)


ZERO = Decimal('0')
TWO_PLACES = Decimal('0.01')

# UK VAT divisor — applied uniformly across all Etsy revenue per the
# v1 simplification (see module docstring).
ETSY_VAT_RATE = Decimal('0.20')

# Etsy rate card v1 (verified from Etsy seller fee documentation
# 2026-05-08). Tagged with this string in fee_source so v2 swaps to
# 'etsy_api_v3' cleanly when we wire per-receipt fee data.
TRANSACTION_FEE_RATE  = Decimal('0.065')   # 6.5% on price + shipping
PAYMENT_PROC_RATE     = Decimal('0.04')    # 4% on order total
PAYMENT_PROC_FIXED    = Decimal('0.20')    # +£0.20 per transaction

# Listing fee — $0.20 / 4 months / listing. Cannot be amortised
# correctly without knowing each listing's full-lifecycle sales
# distribution. Set to zero in v1 so the math is honest; surfaced via
# fee_source string. Material magnitude (£0.025/order at typical
# velocity) so its absence isn't a meaningful misstatement.
LISTING_FEE_PER_UNIT = Decimal('0')


@dataclass
class EtsyMargin:
    """Twin of core.amazon_intel.margin.per_sku.SkuMargin. Field-for-field
    so Manufacture's MarginRow type accepts both."""
    asin: str                                  # Etsy listing_id as string
    marketplace: str                           # always 'ETSY'
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
    fee_source: str
    cost_source: str
    is_composite: bool
    confidence: str


def _pct(numer: Decimal, denom: Decimal) -> Optional[Decimal]:
    if denom is None or denom == 0:
        return None
    return (Decimal('100') * numer / denom).quantize(TWO_PLACES)


def _confidence(cost_source: str, m_number: Optional[str]) -> str:
    """HIGH if both override+m_number, MEDIUM if one, LOW if neither."""
    has_override = cost_source == 'override'
    has_m = bool(m_number)
    if has_override and has_m:
        return 'HIGH'
    if has_override or has_m:
        return 'MEDIUM'
    return 'LOW'


def _compute_fees(price_total: Decimal, shipping: Decimal, units: int) -> Decimal:
    """Etsy rate card v1: transaction (price+shipping × 6.5%) +
    payment processing (total × 4% + £0.20 per transaction).
    Listing fee = 0, off-site ads = 0 in v1.
    Returns total fees in marketplace currency.
    """
    if units <= 0:
        return ZERO
    transaction_fee = (price_total + shipping) * TRANSACTION_FEE_RATE
    payment_fee = (price_total + shipping) * PAYMENT_PROC_RATE + (PAYMENT_PROC_FIXED * units)
    return (transaction_fee + payment_fee).quantize(TWO_PLACES)


def _fetch_sales_aggregate(
    lookback_days: int,
    shop_id: Optional[int] = None,
) -> dict[int, dict]:
    """
    Aggregate etsy_sales by listing_id over the lookback window.
    Returns dict keyed by listing_id with units / price_total / shipping_total.
    """
    sql = """
        SELECT listing_id,
               SUM(quantity)                AS units,
               SUM(price * quantity)        AS gross_price,
               SUM(shipping)                AS gross_shipping,
               SUM(total)                   AS gross_total
          FROM etsy_sales
         WHERE listing_id IS NOT NULL
           AND sale_date >= NOW() - make_interval(days => %(days)s)
    """
    params: dict = {'days': lookback_days}
    if shop_id:
        sql += " AND shop_id = %(shop_id)s"
        params['shop_id'] = shop_id
    sql += " GROUP BY listing_id"

    out: dict[int, dict] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            for lid, units, price_total, shipping, gross_total in cur.fetchall():
                if not units:
                    continue
                out[int(lid)] = {
                    'units': int(units),
                    'price_total': Decimal(str(price_total or 0)),
                    'shipping_total': Decimal(str(shipping or 0)),
                    'gross_total': Decimal(str(gross_total or 0)),
                }
    return out


def _fetch_ad_spend_prorated(
    lookback_days: int,
) -> tuple[dict[int, Decimal], set[str]]:
    """
    Sum ad spend per listing_id over the lookback window, pro-rating
    monthly upload windows that only partially overlap the lookback.

    Returns ``(spend_by_listing, sources_seen)``.

    Pro-ration math: for a single etsy_ad_spend row with period
    [period_start, period_end] (inclusive), and a lookback window
    [lookback_start, lookback_end]:

        period_days   = period_end - period_start + 1
        overlap_start = MAX(period_start, lookback_start)
        overlap_end   = MIN(period_end,   lookback_end)
        overlap_days  = MAX(0, overlap_end - overlap_start + 1)
        contribution  = spend_gbp × overlap_days / period_days

    Done in SQL with ``LEAST/GREATEST`` so the database does the
    arithmetic in one round-trip; a 30-day window straddling two
    monthly uploads correctly contributes from both.
    """
    today_d = date.today()
    lookback_start = today_d - timedelta(days=lookback_days)
    lookback_end = today_d

    sql = """
        SELECT listing_id,
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
          FROM etsy_ad_spend
         WHERE daterange(period_start, period_end + 1, '[)')
            && daterange(%(lb_start)s::date, %(lb_end)s::date + 1, '[)')
         GROUP BY listing_id
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
                for lid, prorated, src_csv in cur.fetchall():
                    if prorated is None:
                        continue
                    out[int(lid)] = Decimal(str(prorated)).quantize(TWO_PLACES)
                    if src_csv:
                        for s in src_csv.split(','):
                            if s.strip():
                                sources.add(s.strip())
    except Exception as exc:
        # Table may not exist yet on a fresh deploy if migrations
        # haven't been re-run; degrade gracefully to "no ad data"
        # rather than 500-ing the whole margin endpoint.
        logger.warning('etsy_ad_spend lookup failed (treating as no data): %s', exc)
    return out, sources


def _fetch_listing_metadata(listing_ids: list[int]) -> dict[int, dict]:
    """Fetch m_number + sku + title for the given listing_ids."""
    if not listing_ids:
        return {}
    out: dict[int, dict] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT listing_id, m_number, sku, title
                  FROM etsy_listings
                 WHERE listing_id = ANY(%s)
                """,
                (listing_ids,),
            )
            for lid, m_number, sku, title in cur.fetchall():
                out[int(lid)] = {
                    'm_number': m_number,
                    'sku': sku,
                    'title': title,
                }
    return out


async def compute_margins(
    lookback_days: int = 30,
    shop_id: Optional[int] = None,
) -> tuple[list[EtsyMargin], dict]:
    """
    Per-listing margin breakdown for Etsy. One row per listing_id.

    Currency: returns Decimals; route layer converts to floats. Etsy is
    GBP-native for NBNE today, so no FX conversion is applied. The
    response shape declares ``currency: 'GBP'`` and includes the same
    fx_rate_used dict the Amazon engine returns (with all rates = 1.0
    for Etsy) to keep field-for-field parity with the combined view.

    Returns ``(margins, ad_meta)`` where ``ad_meta`` is::

        {
          'has_ad_data':  bool,        # True if any listing has spend > 0
          'ad_sources':   list[str],   # ['manual_paste_v1', ...]
        }

    The route layer uses this to flip the response-level
    ``off_site_ads_excluded`` flag and stamp ``ad_data_source`` so the
    consumer can show provenance.
    """
    sales = _fetch_sales_aggregate(lookback_days, shop_id=shop_id)
    if not sales:
        return [], {'has_ad_data': False, 'ad_sources': []}

    listing_meta = _fetch_listing_metadata(list(sales.keys()))
    ad_spend_by_listing, ad_sources = _fetch_ad_spend_prorated(lookback_days)

    # Pull COGS for every M-number we resolved. marketplace='' tells
    # Manufacture to use the default UK warehouse cost — Etsy ships
    # from the same facility as Amazon UK with the same DHL profile,
    # so per-marketplace overrides aren't applied here.
    m_numbers = sorted({
        m['m_number']
        for m in listing_meta.values()
        if m.get('m_number')
    })
    costs, _overhead_ctx = (
        await get_costs_bulk(m_numbers, marketplace='')
        if m_numbers else ({}, {})
    )

    results: list[EtsyMargin] = []
    for listing_id, agg in sales.items():
        units         = agg['units']
        gross_native  = agg['gross_total']
        price_total   = agg['price_total']
        shipping_tot  = agg['shipping_total']

        # VAT — uniform 20% per the v1 simplification
        net = (gross_native / (Decimal('1') + ETSY_VAT_RATE)).quantize(TWO_PLACES)

        meta = listing_meta.get(listing_id, {})
        m_number = meta.get('m_number')

        # Fees — Etsy rate card v1
        fees_total_native = _compute_fees(price_total, shipping_tot, units)
        # Apply VAT divisor to fees too — Etsy charges VAT on its fees
        # for UK sellers; for accounting parity treat the fee number
        # as ex-VAT alongside the revenue. This matches the Amazon
        # engine where the fee number is also ex-VAT.
        fees_total = (fees_total_native / (Decimal('1') + ETSY_VAT_RATE)).quantize(TWO_PLACES)
        fees_per_unit = (fees_total / units).quantize(TWO_PLACES) if units else None

        # COGS — from Manufacture
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

        # ad_spend — from etsy_ad_spend (manual paste v1, prorated to
        # the lookback window). Already in GBP at ingest time. Empty
        # dict when no uploads exist yet, in which case we still
        # report ad_spend=0 and the route layer leaves the
        # ``off_site_ads_excluded: true`` flag set.
        ad_spend = ad_spend_by_listing.get(listing_id, ZERO)

        # Margin arithmetic
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

        results.append(EtsyMargin(
            asin=str(listing_id),
            marketplace='ETSY',
            m_number=m_number,
            units=units,
            gross_revenue=gross_native.quantize(TWO_PLACES),
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
            fee_source='etsy_rate_card_v1',
            cost_source=cost_source,
            is_composite=is_composite,
            confidence=_confidence(cost_source, m_number),
        ))

    has_ad_data = any(m.ad_spend > 0 for m in results)
    ad_meta = {
        'has_ad_data': has_ad_data,
        'ad_sources': sorted(ad_sources) if has_ad_data else [],
    }
    return results, ad_meta


def margin_to_dict(m: EtsyMargin) -> dict:
    """JSON-safe — Decimals to floats, identical to Amazon engine."""
    d = asdict(m)
    for k, v in list(d.items()):
        if isinstance(v, Decimal):
            d[k] = float(v)
    return d


def bucket_margins(margins: list[EtsyMargin]) -> dict:
    """Same bucket shape as Amazon engine for cross-channel summary parity.

    Surfaces ``total_loss_bleed`` (negative-only sum) and
    ``top_loss_makers`` (top 5 by absolute £ loss) so the frontend can
    show a "biggest bleeders" panel without post-processing results.
    Toby's framing 2026-05-08: the endpoint exists to spot which SKUs
    are loss-making — bake that into the summary.
    """
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
