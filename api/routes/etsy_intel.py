"""
Etsy Intelligence API routes.

Mounted at /etsy/* in the Deek FastAPI app.
"""
import os
import secrets
import hashlib
import base64
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict
from typing import Optional
import logging
import httpx

from api.middleware.auth import verify_api_key

router = APIRouter(prefix="/etsy", tags=["Etsy Intelligence"])

log = logging.getLogger(__name__)

ETSY_AUTH_URL = 'https://www.etsy.com/oauth/connect'
ETSY_TOKEN_URL = 'https://api.etsy.com/v3/public/oauth/token'
ETSY_SCOPES = 'transactions_r shops_r'


@router.get("/health")
async def etsy_health():
    """Module health check."""
    from core.etsy_intel.db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM etsy_shops")
                shops = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM etsy_listings")
                listings = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM etsy_sales")
                sales = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM etsy_listing_snapshots")
                snapshots = cur.fetchone()[0]
        return {
            "status": "ok",
            "module": "etsy_intelligence",
            "counts": {
                "shops": shops,
                "listings": listings,
                "sales": sales,
                "snapshots": snapshots,
            },
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── OAuth 2.0 ────────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()
    return verifier, challenge


@router.get("/oauth/connect")
async def oauth_connect():
    """Initiate Etsy OAuth 2.0 flow. Redirects to Etsy consent page."""
    from core.etsy_intel.db import save_oauth_state

    api_key = os.getenv('ETSY_API_KEY', '')
    redirect_uri = os.getenv('ETSY_OAUTH_REDIRECT_URI', '')
    if not api_key or not redirect_uri:
        raise HTTPException(500, 'ETSY_API_KEY and ETSY_OAUTH_REDIRECT_URI must be set')

    state = secrets.token_urlsafe(32)
    verifier, challenge = _generate_pkce()

    # Store state + verifier for callback validation
    save_oauth_state(state, verifier)

    params = {
        'response_type': 'code',
        'client_id': api_key,
        'redirect_uri': redirect_uri,
        'scope': ETSY_SCOPES,
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    }
    auth_url = f'{ETSY_AUTH_URL}?' + '&'.join(
        f'{k}={httpx.URL("", params={k: v}).params[k]}' for k, v in params.items()
    )
    # Build URL properly
    from urllib.parse import urlencode
    auth_url = f'{ETSY_AUTH_URL}?{urlencode(params)}'

    return RedirectResponse(url=auth_url)


@router.get("/oauth/callback")
async def oauth_callback(code: str = Query(...), state: str = Query(...)):
    """Handle Etsy OAuth callback. Exchanges code for tokens."""
    from core.etsy_intel.db import get_oauth_state, save_oauth_token

    # Validate state
    stored = get_oauth_state(state)
    if not stored:
        raise HTTPException(400, 'Invalid or expired OAuth state')

    api_key = os.getenv('ETSY_API_KEY', '')
    redirect_uri = os.getenv('ETSY_OAUTH_REDIRECT_URI', '')

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(ETSY_TOKEN_URL, json={
            'grant_type': 'authorization_code',
            'client_id': api_key,
            'redirect_uri': redirect_uri,
            'code': code,
            'code_verifier': stored['code_verifier'],
        })

        if resp.status_code != 200:
            detail = resp.text
            raise HTTPException(502, f'Etsy token exchange failed: {detail}')

        data = resp.json()

    access_token = data['access_token']
    refresh_token = data['refresh_token']
    expires_in = data.get('expires_in', 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Extract user_id from token (format: "user_id.token_string")
    try:
        user_id = int(access_token.split('.')[0])
    except (ValueError, IndexError):
        user_id = 1  # fallback

    save_oauth_token(
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=ETSY_SCOPES,
    )

    return HTMLResponse(content=f"""
    <html><body style="font-family: sans-serif; max-width: 600px; margin: 40px auto;">
    <h2>Etsy OAuth Connected</h2>
    <p>Successfully authenticated with Etsy.</p>
    <p>User ID: {user_id}</p>
    <p>Scopes: {ETSY_SCOPES}</p>
    <p>Token expires: {expires_at.strftime('%Y-%m-%d %H:%M UTC')}</p>
    <p>You can now run <code>POST /etsy/sync</code> to fetch sales data.</p>
    </body></html>
    """)


@router.get("/oauth/status")
async def oauth_status():
    """Check OAuth token status."""
    from core.etsy_intel.db import get_oauth_token

    token = get_oauth_token()
    if not token:
        return {
            'connected': False,
            'message': 'No OAuth token. Visit /etsy/oauth/connect to authenticate.',
        }

    expires_at = token['expires_at']
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    expired = now >= expires_at

    return {
        'connected': True,
        'expired': expired,
        'user_id': token['user_id'],
        'scopes': token['scopes'],
        'expires_at': expires_at.isoformat(),
        'has_refresh_token': bool(token['refresh_token']),
    }


# ── Sync ─────────────────────────────────────────────────────────────────────

@router.post("/sync")
async def trigger_sync():
    """Trigger a full sync from Etsy API."""
    from core.etsy_intel.sync import sync_all
    result = await sync_all()
    return result


# ── Shops ────────────────────────────────────────────────────────────────────

@router.get("/shops")
async def list_shops():
    """List all synced Etsy shops."""
    from core.etsy_intel.db import get_shops
    return {"shops": get_shops()}


# ── Listings ─────────────────────────────────────────────────────────────────

@router.get("/listings")
async def list_listings(
    shop_id: Optional[int] = Query(None),
    state: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
    max_score: Optional[float] = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
):
    """List listings with optional filters."""
    from core.etsy_intel.db import get_listings
    return get_listings(
        shop_id=shop_id, state=state,
        min_score=min_score, max_score=max_score,
        limit=limit, offset=offset,
    )


@router.get("/listings/{listing_id}")
async def get_listing_detail(listing_id: int):
    """Single listing detail."""
    from core.etsy_intel.db import get_listing
    listing = get_listing(listing_id)
    if not listing:
        raise HTTPException(404, f"No listing found with ID {listing_id}")
    return listing


# ── Sales (cross-module read for manufacture sales-velocity feature) ────────

@router.get("/sales")
async def list_sales(
    days: int = Query(
        30, ge=1, le=365,
        description="Rolling window size in days. Default 30.",
    ),
    shop_id: Optional[int] = Query(
        None,
        description="Filter to a single shop. Default: all configured shops.",
    ),
    _: bool = Depends(verify_api_key),
):
    """
    Pre-aggregated Etsy sales for the last `days` days, grouped by listing_id.

    Returns one row per Etsy listing that had any sales in the window, with
    the listing's stored SKU plus total units. Built for the manufacture app's
    Sales Velocity module (Phase 2B.3) which consumes it via HTTP as a
    cross-module read — manufacture does not query Deek's Postgres directly,
    per the hard rule in `CLAUDE.md`.

    Requires `X-API-Key` header matching `DEEK_API_KEY`. The other `/etsy/*`
    routes are currently unauthenticated; this endpoint is explicitly gated
    because it crosses a module boundary.

    Defensive behaviour: rows where `etsy_listings.sku` is NULL or contains
    a comma (indicating Deek's `skus[0]` ingest collapsed a multi-SKU
    variation — see `core/etsy_intel/sync.py::_parse_receipts`) are
    excluded from the result and counted in the returned `skipped_*`
    fields so callers can detect data-quality regressions.
    """
    from core.etsy_intel.db import get_conn

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT el.shop_id,
                           el.listing_id,
                           el.sku AS external_sku,
                           SUM(es.quantity)::int AS total_quantity,
                           MIN(es.sale_date) AS first_sale_date,
                           MAX(es.sale_date) AS last_sale_date
                    FROM etsy_sales es
                    JOIN etsy_listings el ON el.listing_id = es.listing_id
                    WHERE es.sale_date >= NOW() - make_interval(days => %s)
                      AND (%s IS NULL OR el.shop_id = %s)
                    GROUP BY el.shop_id, el.listing_id, el.sku
                    ORDER BY el.listing_id
                """
                cur.execute(sql, (days, shop_id, shop_id))
                raw_rows = cur.fetchall()
    except Exception as e:
        log.exception("Failed to query etsy_sales aggregate")
        raise HTTPException(500, f"etsy_sales query failed: {e}")

    rows = []
    skipped_null_sku = 0
    skipped_multi_sku = 0
    for shop, listing, sku, qty, first_sale, last_sale in raw_rows:
        if sku is None or sku == "":
            skipped_null_sku += 1
            continue
        if "," in sku:
            # Deek's ingest collapsed a multi-SKU variation into a single
            # cell. We cannot safely attribute per-variation sales without a
            # schema change upstream — skip and count, so a regression shows.
            log.warning(
                "etsy /sales: skipping listing %s with multi-SKU value %r "
                "(expected single-SKU-per-listing model)",
                listing, sku,
            )
            skipped_multi_sku += 1
            continue
        rows.append({
            "shop_id": shop,
            "listing_id": listing,
            "external_sku": sku,
            "total_quantity": qty,
            "first_sale_date": first_sale.isoformat() if first_sale else None,
            "last_sale_date": last_sale.isoformat() if last_sale else None,
        })

    window_end = datetime.now(timezone.utc)
    return {
        "rows": rows,
        "window_days": days,
        "window_end": window_end.isoformat(),
        "shop_id_filter": shop_id,
        "row_count": len(rows),
        "skipped_null_sku": skipped_null_sku,
        "skipped_multi_sku": skipped_multi_sku,
    }


# ── Transaction-level sales (cross-module read for Ledger daily sync) ────────

@router.get("/sales/transactions")
async def list_sales_transactions(
    days: int = Query(
        7, ge=1, le=365,
        description="Rolling window size in days. Default 7.",
    ),
    shop_id: Optional[int] = Query(
        None,
        description="Filter to a single shop. Default: all configured shops.",
    ),
    _: bool = Depends(verify_api_key),
):
    """
    Transaction-level Etsy sales for the last `days` days.

    Returns one row per transaction with individual pricing. Built for
    Ledger's daily polling framework which needs per-transaction prices,
    quantities, shipping, and discounts to compute revenue.

    Requires `X-API-Key` header matching `DEEK_API_KEY`.
    """
    from core.etsy_intel.db import get_conn

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT es.transaction_id,
                           es.listing_id,
                           el.sku,
                           el.title,
                           es.price,
                           es.quantity,
                           es.shipping,
                           es.discount,
                           es.total,
                           es.sale_date,
                           COALESCE(el.currency, 'GBP') AS currency
                    FROM etsy_sales es
                    JOIN etsy_listings el ON el.listing_id = es.listing_id
                    WHERE es.sale_date >= NOW() - make_interval(days => %s)
                      AND (%s IS NULL OR es.shop_id = %s)
                      AND COALESCE(es.status, 'paid') NOT IN ('cancelled', 'refunded')
                    ORDER BY es.sale_date DESC
                """
                cur.execute(sql, (days, shop_id, shop_id))
                cols = [d[0] for d in cur.description]
                raw_rows = cur.fetchall()
    except Exception as e:
        log.exception("Failed to query etsy_sales transactions")
        raise HTTPException(500, f"etsy_sales transaction query failed: {e}")

    rows = []
    for row in raw_rows:
        r = dict(zip(cols, row))
        # Normalise dates to ISO date strings
        if r.get("sale_date") and hasattr(r["sale_date"], "date"):
            r["sale_date"] = r["sale_date"].date().isoformat()
        elif r.get("sale_date") and hasattr(r["sale_date"], "isoformat"):
            r["sale_date"] = r["sale_date"].isoformat()
        # Coerce Decimals to float for JSON
        for k in ("price", "shipping", "discount", "total"):
            if r.get(k) is not None:
                r[k] = float(r[k])
        rows.append(r)

    return rows


# ── Underperformers ──────────────────────────────────────────────────────────

@router.get("/underperformers")
async def underperformers(
    max_score: float = Query(5.0),
    limit: int = Query(20, le=100),
):
    """Listings with health score below threshold, worst first."""
    from core.etsy_intel.db import get_listings
    return get_listings(max_score=max_score, limit=limit)


# ── Reports ──────────────────────────────────────────────────────────────────

@router.get("/report/latest")
async def latest_report():
    """Latest health report."""
    from core.etsy_intel.reports import generate_report
    return generate_report()


# ── Memory Indexing ──────────────────────────────────────────────────────────

@router.post("/index-to-memory")
async def index_to_memory():
    """Push Etsy Intelligence context into Deek memory."""
    from core.etsy_intel.reports import build_deek_context
    import httpx
    import os

    context = build_deek_context()
    deek_url = os.getenv('DEEK_API_URL') or os.getenv('CAIRN_API_URL', 'http://localhost:8765')

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f'{deek_url}/memory/write',
                json={
                    'project': 'etsy-intelligence',
                    'query': 'Etsy Intelligence weekly context snapshot',
                    'decision': context['summary_text'],
                    'rejected': '',
                    'outcome': 'committed',
                    'model': 'system',
                    'files_changed': [],
                },
                timeout=10.0,
            )
            resp.raise_for_status()
        return {'status': 'ok', 'summary': context['summary_text']}
    except Exception as e:
        return {'status': 'partial', 'context': context, 'memory_error': str(e)}


# ── Deek Context ────────────────────────────────────────────────────────────

@router.get("/cairn/context")
async def deek_context():
    """Module context endpoint per DEEK_MODULES.md spec."""
    from core.etsy_intel.reports import build_deek_context
    return build_deek_context()


# ── Margin (per-listing profitability — mirrors /ami/margin/per-sku) ────────

@router.get("/margin/per-sku", dependencies=[Depends(verify_api_key)])
async def margin_per_sku(
    lookback_days: int = Query(30, ge=1, le=365),
    shop_id: Optional[int] = Query(
        None,
        description=(
            "Optional shop_id filter — NBNE has a single Etsy shop "
            "today (NorthByNorthEastSign), so omitting is the normal "
            "case. Reserved for future per-shop breakdown."
        ),
    ),
    min_units: int = Query(0, ge=0),
):
    """
    Per-listing margin breakdown for Etsy. One row per listing_id.

    **Currency contract:** every monetary field is GBP, regardless of
    buyer country. Etsy is GBP-native for NBNE today; non-GBP receipts
    aren't currently captured (etsy_sales has no currency column),
    treated as GBP at face value. ``fx_rate_used`` is included for
    parity with /ami/margin/per-sku — all rates are 1.0 since Etsy
    runs single-currency for now.

    **Fee model — Etsy rate card v1:**
      - Transaction fee: 6.5% of (price + shipping)
      - Payment processing: 4% of total + £0.20 per transaction
      - Listing fee: 0 (cannot be amortised correctly per-unit; v2)
      - Off-site Ads: 0 — see ``off_site_ads_excluded`` below

    **VAT:** 20% UK rate applied uniformly across all sales (UK
    dominant; per-order country is a v2 follow-up). The Amazon engine
    uses the same convention.

    **Confidence:** HIGH if cost_source=override AND m_number resolved;
    MEDIUM if exactly one missing; LOW if both.

    **Known under-statements (declared in response):**
      - ``off_site_ads_excluded: true`` — shops auto-enrolled in Etsy
        Off-site Ads pay an additional 12-15% on those orders. v1
        treats every order as direct.
      - ``listing_fee_excluded: true`` — $0.20 per listing per 4 months
        amortisation is a v2 follow-up.
    """
    from core.etsy_intel.margin.per_sku import (
        compute_margins, margin_to_dict, bucket_margins,
    )
    margins, ad_meta = await compute_margins(
        lookback_days=lookback_days, shop_id=shop_id,
    )
    if min_units:
        margins = [m for m in margins if m.units >= min_units]
    response: dict = {
        'marketplace': 'ETSY',
        'lookback_days': lookback_days,
        'currency': 'GBP',
        'fx_rate_used': {'GBP': 1.0},
        'listing_fee_excluded': True,
        'fee_source': 'etsy_rate_card_v1',
        'summary': bucket_margins(margins),
        'results': [margin_to_dict(m) for m in margins],
    }
    # Off-site ads / ad-data provenance: if any ad-spend record fed
    # into this response, drop the ``off_site_ads_excluded`` flag and
    # stamp the source(s) so the consumer can show provenance.
    if ad_meta.get('has_ad_data'):
        response['ad_data_source'] = ','.join(ad_meta.get('ad_sources') or [])
    else:
        response['off_site_ads_excluded'] = True
    return response


@router.get("/margin/buckets", dependencies=[Depends(verify_api_key)])
async def margin_buckets(
    lookback_days: int = Query(30, ge=1, le=365),
    shop_id: Optional[int] = Query(None),
):
    """Summary-only — cheap to poll for the combined-view top-line."""
    from core.etsy_intel.margin.per_sku import (
        compute_margins, bucket_margins,
    )
    margins, ad_meta = await compute_margins(
        lookback_days=lookback_days, shop_id=shop_id,
    )
    response: dict = {
        'marketplace': 'ETSY',
        'lookback_days': lookback_days,
        'currency': 'GBP',
        'fx_rate_used': {'GBP': 1.0},
        'summary': bucket_margins(margins),
    }
    if ad_meta.get('has_ad_data'):
        response['ad_data_source'] = ','.join(ad_meta.get('ad_sources') or [])
    else:
        response['off_site_ads_excluded'] = True
    return response


# ── Ad spend ingestion + listings lookup ───────────────────────────────────

class _AdSpendRow(BaseModel):
    """Single per-listing ad-spend row in a manual-paste batch."""
    model_config = ConfigDict(extra='ignore')
    listing_id:     int
    views:          Optional[int] = None
    clicks:         Optional[int] = None
    orders_attrib:  Optional[int] = None
    revenue_attrib: Optional[float] = None
    spend:          float


class _AdSpendBatch(BaseModel):
    """Whole-batch payload from Manufacture's paste form."""
    model_config = ConfigDict(extra='ignore')
    period_start:    str   # YYYY-MM-DD
    period_end:      str   # YYYY-MM-DD
    source_currency: str = 'USD'
    source:          str = 'manual_paste_v1'
    uploaded_by:     Optional[str] = None
    rows:            list[_AdSpendRow]


@router.post("/ad-spend/ingest", dependencies=[Depends(verify_api_key)])
async def ad_spend_ingest(payload: _AdSpendBatch):
    """
    Ingest a batch of per-listing ad-spend rows from the Manufacture
    paste form. Behaviour per the brief:

      1. Validate period_end >= period_start, listing_ids are ints,
         spend >= 0.
      2. Resolve a single FX rate at period midpoint (cached for the
         batch) using the historical-aware ``convert_to_gbp(amount,
         currency, as_of=...)`` helper.
      3. Upsert with ON CONFLICT (listing_id, period_start, period_end)
         DO UPDATE — re-uploads of the same window replace cleanly.
      4. listing_ids that don't exist in etsy_listings are returned in
         ``unknown_listings``; the valid rows still upsert.
      5. Wrap in one transaction so partial failures leave prior data
         intact.
    """
    from datetime import date as _date, timedelta as _timedelta
    from decimal import Decimal as _Dec
    from core.amazon_intel.fx import get_rate

    try:
        period_start = _date.fromisoformat(payload.period_start)
        period_end = _date.fromisoformat(payload.period_end)
    except ValueError as exc:
        raise HTTPException(422, f'invalid period date: {exc}')
    if period_end < period_start:
        raise HTTPException(422, 'period_end must be >= period_start')

    if not payload.rows:
        raise HTTPException(422, 'rows: at least one row required')
    for r in payload.rows:
        if r.spend is None or r.spend < 0:
            raise HTTPException(
                422,
                f'spend must be >= 0 (listing {r.listing_id}: {r.spend})',
            )

    # FX at period midpoint — historical-aware lookup against
    # ami_fx_rates so April spend uploaded in May uses an April rate.
    midpoint = period_start + _timedelta(
        days=(period_end - period_start).days // 2,
    )
    currency_code = (payload.source_currency or 'USD').upper()
    fx_rate_decimal = get_rate(currency_code, as_of=midpoint)
    fx_rate = float(fx_rate_decimal)

    from core.etsy_intel.db import get_conn as _get_conn
    unknown: list[int] = []
    rows_upserted = 0
    rows_replaced = 0
    total_spend_gbp = _Dec('0')

    with _get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Find which listing_ids exist
            input_listing_ids = sorted({r.listing_id for r in payload.rows})
            cur.execute(
                "SELECT listing_id FROM etsy_listings WHERE listing_id = ANY(%s)",
                (input_listing_ids,),
            )
            valid_ids = {row[0] for row in cur.fetchall()}
            unknown = sorted(set(input_listing_ids) - valid_ids)

            for r in payload.rows:
                if r.listing_id not in valid_ids:
                    continue
                spend_native = _Dec(str(r.spend))
                # Convert native → GBP; GBP source short-circuits to
                # the input. fx_rate=1.0 in that case.
                if currency_code == 'GBP':
                    spend_gbp = spend_native
                else:
                    spend_gbp = (spend_native / fx_rate_decimal)
                spend_gbp = spend_gbp.quantize(_Dec('0.01'))
                total_spend_gbp += spend_gbp

                # Detect replace vs new
                cur.execute(
                    """
                    SELECT 1 FROM etsy_ad_spend
                     WHERE listing_id = %s AND period_start = %s AND period_end = %s
                    """,
                    (r.listing_id, period_start, period_end),
                )
                existed = cur.fetchone() is not None

                cur.execute(
                    """
                    INSERT INTO etsy_ad_spend
                        (listing_id, period_start, period_end,
                         views, clicks, orders_attrib, revenue_attrib,
                         spend, spend_gbp,
                         source_currency, fx_rate_used,
                         source, uploaded_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (listing_id, period_start, period_end)
                    DO UPDATE SET
                        views           = EXCLUDED.views,
                        clicks          = EXCLUDED.clicks,
                        orders_attrib   = EXCLUDED.orders_attrib,
                        revenue_attrib  = EXCLUDED.revenue_attrib,
                        spend           = EXCLUDED.spend,
                        spend_gbp       = EXCLUDED.spend_gbp,
                        source_currency = EXCLUDED.source_currency,
                        fx_rate_used    = EXCLUDED.fx_rate_used,
                        source          = EXCLUDED.source,
                        uploaded_by     = EXCLUDED.uploaded_by,
                        uploaded_at     = NOW()
                    """,
                    (
                        r.listing_id, period_start, period_end,
                        r.views, r.clicks, r.orders_attrib, r.revenue_attrib,
                        spend_native, spend_gbp,
                        currency_code, fx_rate,
                        payload.source, payload.uploaded_by,
                    ),
                )
                rows_upserted += 1
                if existed:
                    rows_replaced += 1
        conn.commit()

    return {
        'period_start':    period_start.isoformat(),
        'period_end':      period_end.isoformat(),
        'source_currency': currency_code,
        'fx_rate_used':    fx_rate,
        'fx_as_of':        midpoint.isoformat(),
        'rows_received':   len(payload.rows),
        'rows_upserted':   rows_upserted,
        'rows_replaced':   rows_replaced,
        'unknown_listings': unknown,
        'total_spend_gbp': float(total_spend_gbp),
    }


class _LookupBatch(BaseModel):
    """Title→listing_id resolver input. Either ``titles`` or ``skus``
    (or both) — review item 5: SKU is a much cleaner matcher when
    available."""
    model_config = ConfigDict(extra='ignore')
    titles: Optional[list[str]] = None
    skus:   Optional[list[str]] = None


@router.post("/listings/lookup", dependencies=[Depends(verify_api_key)])
async def listings_lookup(payload: _LookupBatch):
    """
    Resolve titles or SKUs to listing_ids. Used by Manufacture's
    paste form to convert "what the user pasted" into the canonical
    keys the ad-spend ingest endpoint expects.

    Resolution order per input:

      - SKUs:  exact match (case-insensitive)  → ``match_type='sku'``
      - Title: exact (case-sensitive)          → ``match_type='exact'``
               case-insensitive                → ``match_type='case_insensitive'``
               trigram similarity ≥ 0.4        → ``match_type='fuzzy'``
                                                  (or ``'ambiguous'`` if
                                                   multiple within 0.05
                                                   of the top score)

    State is included in the response so the consumer can flag
    matches against inactive listings.
    """
    titles = payload.titles or []
    skus = payload.skus or []
    if not titles and not skus:
        raise HTTPException(
            422, 'provide at least one of titles[] or skus[]',
        )

    from core.etsy_intel.db import get_conn as _get_conn
    matches: list[dict] = []
    unmatched_titles: list[str] = []
    unmatched_skus: list[str] = []

    with _get_conn() as conn:
        with conn.cursor() as cur:
            # ── SKUs: case-insensitive exact match ─────────────────────
            if skus:
                normalised = [s.strip().lower() for s in skus if s and s.strip()]
                cur.execute(
                    """
                    SELECT listing_id, sku, title, m_number, state
                      FROM etsy_listings
                     WHERE LOWER(TRIM(sku)) = ANY(%s)
                    """,
                    (normalised,),
                )
                by_sku = {
                    row[1].strip().lower(): row
                    for row in cur.fetchall()
                    if row[1]
                }
                for raw in skus:
                    key = (raw or '').strip().lower()
                    if key in by_sku:
                        lid, sku, title, m_number, state = by_sku[key]
                        matches.append({
                            'sku_input':   raw,
                            'sku_matched': sku,
                            'title':       title,
                            'listing_id':  lid,
                            'm_number':    m_number,
                            'state':       state,
                            'match_type':  'sku',
                            'confidence':  1.0,
                        })
                    elif raw and raw.strip():
                        unmatched_skus.append(raw)

            # ── Titles ───────────────────────────────────────────────────
            for raw_title in titles:
                title = (raw_title or '').strip()
                if not title:
                    continue

                # 1. exact (case-sensitive), prefer active
                cur.execute(
                    """
                    SELECT listing_id, sku, title, m_number, state
                      FROM etsy_listings
                     WHERE title = %s
                     ORDER BY (state = 'active') DESC
                     LIMIT 1
                    """,
                    (title,),
                )
                row = cur.fetchone()
                if row:
                    lid, sku, t, m, state = row
                    matches.append({
                        'title_input':   raw_title,
                        'title_matched': t,
                        'sku':           sku,
                        'listing_id':    lid,
                        'm_number':      m,
                        'state':         state,
                        'match_type':    'exact',
                        'confidence':    1.0,
                    })
                    continue

                # 2. case-insensitive
                cur.execute(
                    """
                    SELECT listing_id, sku, title, m_number, state
                      FROM etsy_listings
                     WHERE LOWER(title) = LOWER(%s)
                     ORDER BY (state = 'active') DESC
                     LIMIT 1
                    """,
                    (title,),
                )
                row = cur.fetchone()
                if row:
                    lid, sku, t, m, state = row
                    matches.append({
                        'title_input':   raw_title,
                        'title_matched': t,
                        'sku':           sku,
                        'listing_id':    lid,
                        'm_number':      m,
                        'state':         state,
                        'match_type':    'case_insensitive',
                        'confidence':    0.99,
                    })
                    continue

                # 3. trigram fuzzy — threshold 0.4 (review item 2;
                #    0.85 was way too strict for the typical typo).
                cur.execute(
                    """
                    SELECT listing_id, sku, title, m_number, state,
                           similarity(title, %s) AS score
                      FROM etsy_listings
                     WHERE similarity(title, %s) >= 0.4
                     ORDER BY score DESC, (state = 'active') DESC
                     LIMIT 5
                    """,
                    (title, title),
                )
                rows = cur.fetchall()
                if not rows:
                    unmatched_titles.append(raw_title)
                    continue
                top_lid, top_sku, top_title, top_m, top_state, top_score = rows[0]
                # Ambiguous if multiple within 0.05 of the top
                close = [
                    r for r in rows[1:]
                    if abs(float(r[5]) - float(top_score)) <= 0.05
                ]
                if close:
                    matches.append({
                        'title_input':   raw_title,
                        'match_type':    'ambiguous',
                        'candidates': [
                            {
                                'listing_id': r[0],
                                'sku':        r[1],
                                'title':      r[2],
                                'm_number':   r[3],
                                'state':      r[4],
                                'similarity': float(r[5]),
                            }
                            for r in rows
                        ],
                    })
                else:
                    matches.append({
                        'title_input':   raw_title,
                        'title_matched': top_title,
                        'sku':           top_sku,
                        'listing_id':    top_lid,
                        'm_number':      top_m,
                        'state':         top_state,
                        'match_type':    'fuzzy',
                        'confidence':    float(top_score),
                    })

    return {
        'matches': matches,
        'unmatched': unmatched_titles + unmatched_skus,
    }
