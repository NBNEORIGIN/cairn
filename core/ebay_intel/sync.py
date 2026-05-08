"""
eBay sync runners — populate ebay_listings + ebay_sales from the eBay APIs.

Two syncs:

  sync_listings()  — Inventory API → minimal listings mirror
                     (item_id, sku, title, state). Full catalogue stays
                     on Render. Refreshes m_number from ami_sku_mapping
                     after each sync (same one-statement pattern as the
                     Etsy module uses).

  sync_orders(days_back=N) — Fulfillment API → ebay_sales line items.
                     Default 30-day window; cron drives it every 30
                     minutes during business hours so latency to the
                     margin engine stays low.

Both runners are idempotent: ON CONFLICT updates the existing row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .api_client import EbayClient
from .db import get_conn


log = logging.getLogger(__name__)


# ── Listings sync ──────────────────────────────────────────────────────────

async def sync_listings() -> dict:
    """Pull active listings via the Inventory API; upsert into
    ebay_listings; backfill m_number from ami_sku_mapping.

    Returns a summary dict for logging."""
    async with EbayClient() as client:
        items = await client.get_inventory_items()

    listings_to_upsert: list[dict] = []
    for item in items:
        sku = (item.get('sku') or '').strip() or None
        title = (item.get('product') or {}).get('title') if isinstance(item.get('product'), dict) else None
        availability = item.get('availability') or {}
        # Inventory API doesn't directly expose item_id (that's an
        # offer/listing concept). We look it up via a per-SKU offer call.
        item_id = None
        if sku:
            async with EbayClient() as client:
                offers = await client.get_offers_for_sku(sku)
            # Take the first PUBLISHED offer's listingId; if none is
            # published the SKU is inventory-only (not listed).
            for offer in offers:
                lid = offer.get('listing', {}).get('listingId') if isinstance(offer.get('listing'), dict) else None
                if lid:
                    item_id = int(lid)
                    break
        if not item_id:
            # Skip — inventory item with no live listing
            continue

        listings_to_upsert.append({
            'item_id': item_id,
            'sku':     sku,
            'title':   title,
            'state':   'active',
        })

    upserted = _upsert_listings(listings_to_upsert)
    backfilled = _backfill_m_numbers()

    return {
        'inventory_items_seen': len(items),
        'listings_upserted':    upserted,
        'm_number_backfilled':  backfilled,
    }


def _upsert_listings(listings: list[dict]) -> int:
    """ON CONFLICT (item_id) DO UPDATE."""
    if not listings:
        return 0
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in listings:
                cur.execute(
                    """
                    INSERT INTO ebay_listings
                        (item_id, sku, title, state, last_synced)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (item_id) DO UPDATE SET
                        sku         = EXCLUDED.sku,
                        title       = EXCLUDED.title,
                        state       = EXCLUDED.state,
                        last_synced = NOW()
                    """,
                    (r['item_id'], r.get('sku'), r.get('title'), r.get('state', 'active')),
                )
                n += 1
        conn.commit()
    return n


def _backfill_m_numbers() -> int:
    """Refresh ebay_listings.m_number from ami_sku_mapping (country='EBAY').

    Multi-pass mirroring the Etsy backfill — the Stock Sheet has 272
    EBAY rows but eBay actually has more listings, so we cast a wider
    net than just the literal ETSY-style match:

      pass 1 — ami_sku_mapping where country='EBAY' AND sku matches
      pass 2 — sku is bare M-number AND that M-number exists anywhere
      pass 3 — cross-channel match against ami_sku_mapping with UK priority
      pass 4 — regex extract M-prefix from compound SKUs

    Returns the count of rows updated across all passes."""
    sql = """
    -- pass 1: country='EBAY' exact normalised
    UPDATE ebay_listings l
       SET m_number = m.m_number
      FROM ami_sku_mapping m
     WHERE m.country = 'EBAY'
       AND TRIM(LOWER(m.sku)) = TRIM(LOWER(l.sku))
       AND l.m_number IS DISTINCT FROM m.m_number;

    -- pass 2: sku is bare M-number, exists anywhere in ami_sku_mapping
    UPDATE ebay_listings l
       SET m_number = upper(trim(l.sku))
     WHERE l.m_number IS NULL
       AND l.sku ~ '^[Mm][0-9]{4,}$'
       AND EXISTS (
         SELECT 1 FROM ami_sku_mapping m WHERE m.m_number = upper(trim(l.sku))
       );

    -- pass 3: cross-channel match, UK takes priority
    UPDATE ebay_listings l
       SET m_number = sub.m_number
      FROM (
        SELECT DISTINCT ON (TRIM(LOWER(sku))) TRIM(LOWER(sku)) AS norm_sku, m_number
          FROM ami_sku_mapping
         WHERE m_number IS NOT NULL
         ORDER BY TRIM(LOWER(sku)),
                  CASE country
                    WHEN 'UK' THEN 1 WHEN 'US' THEN 2 WHEN 'CA' THEN 3
                    WHEN 'AU' THEN 4 ELSE 5 END
      ) sub
     WHERE l.m_number IS NULL
       AND l.sku IS NOT NULL
       AND TRIM(LOWER(l.sku)) = sub.norm_sku;

    -- pass 4: regex extract M-prefix
    UPDATE ebay_listings l
       SET m_number = sub.m_match
      FROM (
        SELECT item_id,
               UPPER((regexp_match(sku, '[Mm][0-9]{4,}'))[1]) AS m_match
          FROM ebay_listings
         WHERE m_number IS NULL
           AND sku IS NOT NULL
           AND sku ~ '[Mm][0-9]{4,}'
      ) sub
     WHERE l.item_id = sub.item_id
       AND sub.m_match IS NOT NULL
       AND EXISTS (SELECT 1 FROM ami_sku_mapping m WHERE m.m_number = sub.m_match);
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
    # Return current resolved count for visibility
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(m_number) FROM ebay_listings WHERE m_number IS NOT NULL"
            )
            return int(cur.fetchone()[0] or 0)


# ── Orders sync ────────────────────────────────────────────────────────────

async def sync_orders(days_back: int = 30) -> dict:
    """Pull orders created in the last ``days_back`` days, flatten into
    line-item rows, upsert into ebay_sales."""
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    async with EbayClient() as client:
        orders = await client.get_orders(creation_date_from=since)

    line_rows = list(_flatten_orders(orders))
    upserted = _upsert_sales(line_rows)
    return {
        'orders_pulled': len(orders),
        'lines_upserted': upserted,
        'window_start':  since.isoformat(),
    }


def _flatten_orders(orders: list[dict]):
    """Yield (order, line_item) flattened rows for upsert.

    Strict PII whitelist: order_id / line_item_id / item_id / sku /
    quantities / prices / dates / buyer_country only. NEVER include
    buyer_username / email / shipping_address / phone — Manufacture's
    existing whitelist convention.
    """
    for o in orders:
        order_id = o.get('orderId')
        legacy = o.get('legacyOrderId')
        creation = o.get('creationDate')
        sale_date = _parse_iso(creation)
        ship_addr_country = (
            ((o.get('fulfillmentStartInstructions') or [{}])[0]
              .get('shippingStep') or {})
              .get('shipTo') or {}
        ).get('contactAddress', {}).get('countryCode')
        # If buyer_country isn't on the address, fall back to the
        # buyerCheckoutNotes-adjacent fields. Never read buyer.email
        # or buyer.username.
        order_country = ship_addr_country  # ISO; PII-safe (just country code)

        fulfillment_status = (o.get('orderFulfillmentStatus') or '')
        payment_status = (o.get('orderPaymentStatus') or '')

        line_items = o.get('lineItems') or []
        for li in line_items:
            line_item_id = li.get('lineItemId')
            if not (order_id and line_item_id):
                continue
            item_id_raw = li.get('legacyItemId') or li.get('itemId')
            try:
                item_id = int(item_id_raw) if item_id_raw else None
            except (ValueError, TypeError):
                item_id = None
            sku = (li.get('sku') or '').strip() or None

            quantity = int(li.get('quantity') or 0)
            unit = _money(li.get('lineItemCost'))
            total_price = (Decimal(str(unit)) * quantity).quantize(Decimal('0.01')) if unit is not None else None
            shipping_cost = _money(li.get('deliveryCost', {}).get('shippingCost')) if isinstance(li.get('deliveryCost'), dict) else None
            total_paid = _money(li.get('total'))

            # Per-line fee — eBay sometimes embeds it under
            # pricingSummary.fee.value. Often missing; the margin
            # engine falls back to rate-card when None.
            fees = None
            ps = li.get('pricingSummary') if isinstance(li.get('pricingSummary'), dict) else None
            if ps and isinstance(ps.get('fee'), dict):
                fees = _money(ps.get('fee'))

            currency = (li.get('lineItemCost') or {}).get('currency') if isinstance(li.get('lineItemCost'), dict) else None
            currency = currency or 'GBP'

            yield {
                'order_id':           order_id,
                'legacy_order_id':    legacy,
                'line_item_id':       line_item_id,
                'item_id':            item_id,
                'sku':                sku,
                'quantity':           quantity,
                'unit_price':         unit,
                'total_price':        total_price,
                'shipping_cost':      shipping_cost,
                'total_paid':         total_paid,
                'fees':               fees,
                'currency':           currency,
                'buyer_country':      order_country,
                'fulfillment_status': fulfillment_status,
                'payment_status':     payment_status,
                'sale_date':          sale_date,
            }


def _money(obj: Any) -> Decimal | None:
    """eBay money fields are dicts: {'value': '12.34', 'currency': 'GBP'}.
    Return Decimal value or None."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        v = obj.get('value')
        return Decimal(str(v)) if v is not None else None
    try:
        return Decimal(str(obj))
    except Exception:
        return None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # eBay uses RFC 3339 ('Z' suffix)
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def _upsert_sales(rows: list[dict]) -> int:
    if not rows:
        return 0
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO ebay_sales (
                        order_id, legacy_order_id, line_item_id, item_id, sku,
                        quantity, unit_price, total_price, shipping_cost,
                        total_paid, fees, currency, buyer_country,
                        fulfillment_status, payment_status, sale_date,
                        last_synced
                    ) VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, NOW())
                    ON CONFLICT (order_id, line_item_id) DO UPDATE SET
                        item_id            = EXCLUDED.item_id,
                        sku                = EXCLUDED.sku,
                        quantity           = EXCLUDED.quantity,
                        unit_price         = EXCLUDED.unit_price,
                        total_price        = EXCLUDED.total_price,
                        shipping_cost      = EXCLUDED.shipping_cost,
                        total_paid         = EXCLUDED.total_paid,
                        fees               = EXCLUDED.fees,
                        currency           = EXCLUDED.currency,
                        buyer_country      = EXCLUDED.buyer_country,
                        fulfillment_status = EXCLUDED.fulfillment_status,
                        payment_status     = EXCLUDED.payment_status,
                        sale_date          = EXCLUDED.sale_date,
                        last_synced        = NOW()
                    """,
                    (
                        r['order_id'], r.get('legacy_order_id'), r['line_item_id'],
                        r.get('item_id'), r.get('sku'),
                        r.get('quantity', 0), r.get('unit_price'), r.get('total_price'),
                        r.get('shipping_cost'),
                        r.get('total_paid'), r.get('fees'), r.get('currency'),
                        r.get('buyer_country'),
                        r.get('fulfillment_status'), r.get('payment_status'),
                        r.get('sale_date'),
                    ),
                )
                n += 1
        conn.commit()
    return n
