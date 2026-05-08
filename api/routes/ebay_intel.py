"""
eBay Intelligence API routes.

Mounted at ``/ebay/*`` in the Deek FastAPI app. Mirrors
``api/routes/etsy_intel.py`` for the channel-engine pattern.

Endpoint groups
---------------
  /ebay/oauth/{connect,callback,status}  — consent flow + token state
  /ebay/sync/{listings,orders}           — manual cron triggers
  /ebay/sales                            — Manufacture's velocity adapter
                                           consumes this (replacing its
                                           direct-eBay-API path)
  /ebay/margin/{per-sku,buckets}         — combined-view profitability
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict

from api.middleware.auth import verify_api_key


router = APIRouter(prefix='/ebay', tags=['eBay Intelligence'])
log = logging.getLogger(__name__)


# ── Health ─────────────────────────────────────────────────────────────────

@router.get('/health')
async def ebay_health():
    """Module health — token status + row counts."""
    from core.ebay_intel.db import get_conn
    from core.ebay_intel.api_client import get_status as oauth_status
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM ebay_listings')
                listings = cur.fetchone()[0]
                cur.execute('SELECT COUNT(*) FROM ebay_sales')
                sales = cur.fetchone()[0]
                cur.execute('SELECT COUNT(*) FROM ebay_ad_spend')
                ad_rows = cur.fetchone()[0]
        return {
            'status': 'ok',
            'module': 'ebay_intelligence',
            'oauth':  oauth_status(),
            'counts': {
                'listings':  listings,
                'sales':     sales,
                'ad_spend':  ad_rows,
            },
        }
    except Exception as exc:
        return {'status': 'error', 'detail': str(exc)}


# ── OAuth flow ─────────────────────────────────────────────────────────────

@router.get('/oauth/connect')
async def oauth_connect():
    """Step 1 — redirect Toby to eBay's consent page. He clicks
    "Allow", eBay redirects back to /ebay/oauth/callback with a code.

    Pre-requisites: EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_RU_NAME
    must all be set. EBAY_RU_NAME must be registered against eBay's
    developer dashboard pointing at https://deek.nbnesigns.co.uk/ebay/oauth/callback
    (or whatever Toby chooses).
    """
    from core.ebay_intel.api_client import get_authorization_url
    state = secrets.token_urlsafe(24)
    try:
        url = get_authorization_url(state=state)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    # Stash state on the row so callback can verify (race-free single
    # active consent at a time — Toby clicks once)
    from core.ebay_intel.db import get_conn
    from os import getenv
    env = (getenv('EBAY_ENVIRONMENT') or 'production').lower()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ebay_oauth_tokens
                    (environment, access_token, refresh_token, expires_at, state)
                VALUES (%s, '', '', NOW(), %s)
                ON CONFLICT (environment) DO UPDATE SET
                    state = EXCLUDED.state,
                    updated_at = NOW()
                """,
                (env, state),
            )
            conn.commit()
    return RedirectResponse(url=url)


@router.get('/oauth/callback')
async def oauth_callback(code: str = Query(...), state: str = Query(...)):
    """Step 2 — eBay redirects here with code+state. Verify state,
    exchange code for tokens, persist."""
    from core.ebay_intel.db import get_conn
    from core.ebay_intel.api_client import exchange_code_for_tokens
    from os import getenv
    env = (getenv('EBAY_ENVIRONMENT') or 'production').lower()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT state FROM ebay_oauth_tokens WHERE environment = %s',
                (env,),
            )
            row = cur.fetchone()
    if not row or row[0] != state:
        raise HTTPException(400, 'state mismatch — start /ebay/oauth/connect again')

    try:
        result = await exchange_code_for_tokens(code)
    except Exception as exc:
        raise HTTPException(500, f'token exchange failed: {exc}')
    return HTMLResponse(
        f"""
        <h1>eBay connected</h1>
        <p>Token environment: {result['environment']}</p>
        <p>Expires at: {result['expires_at']}</p>
        <p>You can close this tab.</p>
        """,
        status_code=200,
    )


@router.get('/oauth/status', dependencies=[Depends(verify_api_key)])
async def oauth_status_route():
    from core.ebay_intel.api_client import get_status
    return get_status()


# ── Sync triggers ──────────────────────────────────────────────────────────

@router.post('/sync/listings', dependencies=[Depends(verify_api_key)])
async def sync_listings_route():
    """Pull active listings + backfill m_number. Cron: hourly."""
    from core.ebay_intel.sync import sync_listings
    return await sync_listings()


@router.post('/sync/orders', dependencies=[Depends(verify_api_key)])
async def sync_orders_route(days_back: int = Query(30, ge=1, le=365)):
    """Pull orders created in the last ``days_back`` days. Cron: every
    30 minutes during business hours."""
    from core.ebay_intel.sync import sync_orders
    return await sync_orders(days_back=days_back)


# ── Sales surface (Manufacture velocity adapter consumes this) ─────────────

@router.get('/sales', dependencies=[Depends(verify_api_key)])
async def list_sales(
    days_back: int = Query(30, ge=1, le=365),
    sku: Optional[str] = Query(None),
):
    """List eBay sales line items. Manufacture's sales_velocity adapter
    switches to consume this (replacing its direct-eBay-API path) so
    OAuth lifecycle stays in Deek.

    PII boundary: response excludes buyer_name/email/address. Only
    sku, quantity, line ids, dates, country code (for VAT logic).
    Same whitelist as Manufacture's adapter today.
    """
    from core.ebay_intel.db import get_conn
    sql = """
        SELECT order_id, legacy_order_id, line_item_id, item_id, sku,
               quantity, unit_price, total_price, shipping_cost,
               total_paid, fees, currency, buyer_country,
               fulfillment_status, payment_status, sale_date
          FROM ebay_sales
         WHERE sale_date >= NOW() - make_interval(days => %(days)s)
    """
    params: dict = {'days': days_back}
    if sku:
        sql += ' AND sku = %(sku)s'
        params['sku'] = sku
    sql += ' ORDER BY sale_date DESC'
    rows: list[dict] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                rec = dict(zip(cols, row))
                # JSON-friendly conversions
                for k, v in list(rec.items()):
                    if hasattr(v, 'isoformat'):
                        rec[k] = v.isoformat()
                    elif hasattr(v, 'as_tuple'):  # Decimal
                        rec[k] = float(v)
                rows.append(rec)
    return {
        'count': len(rows),
        'days_back': days_back,
        'sales': rows,
    }


# ── Margin endpoint ────────────────────────────────────────────────────────

@router.get('/margin/per-sku', dependencies=[Depends(verify_api_key)])
async def margin_per_sku(
    lookback_days: int = Query(30, ge=1, le=365),
    min_units: int = Query(0, ge=0),
):
    """Per-listing margin for eBay. One row per item_id. Same response
    shape as /etsy/margin/per-sku and /ami/margin/per-sku — drop into
    Manufacture's combined-view fan-out with one switch line.
    """
    from core.ebay_intel.margin.per_sku import (
        compute_margins, margin_to_dict, bucket_margins,
    )
    margins, ad_meta = await compute_margins(lookback_days=lookback_days)
    if min_units:
        margins = [m for m in margins if m.units >= min_units]
    response: dict = {
        'marketplace': 'EBAY',
        'lookback_days': lookback_days,
        'currency': 'GBP',
        'fx_rate_used': {'GBP': 1.0},
        'fee_source': 'ebay_api_v1+rate_card_v1',
        'summary': bucket_margins(margins),
        'results': [margin_to_dict(m) for m in margins],
    }
    if ad_meta.get('has_ad_data'):
        response['ad_data_source'] = ','.join(ad_meta.get('ad_sources') or [])
    else:
        response['promoted_listings_excluded'] = True
    return response


@router.get('/margin/buckets', dependencies=[Depends(verify_api_key)])
async def margin_buckets(
    lookback_days: int = Query(30, ge=1, le=365),
):
    """Summary-only — cheap to poll for the combined-view top-line."""
    from core.ebay_intel.margin.per_sku import (
        compute_margins, bucket_margins,
    )
    margins, ad_meta = await compute_margins(lookback_days=lookback_days)
    response: dict = {
        'marketplace': 'EBAY',
        'lookback_days': lookback_days,
        'currency': 'GBP',
        'fx_rate_used': {'GBP': 1.0},
        'summary': bucket_margins(margins),
    }
    if ad_meta.get('has_ad_data'):
        response['ad_data_source'] = ','.join(ad_meta.get('ad_sources') or [])
    else:
        response['promoted_listings_excluded'] = True
    return response
