"""
eBay API v1 client with DB-backed OAuth and pagination.

Pattern follows Manufacture's `sales_velocity/adapters/ebay.py` (which
itself was ported from Render's `ebay_auth.py`). Key differences from
Render's pattern:

  * Tokens persist in Postgres (`ebay_oauth_tokens`), not a JSON file
  * Uses ``SELECT ... FOR UPDATE`` to prevent the web+cron refresh race
    that Manufacture's adapter solved historically
  * Async (httpx) — matches Etsy's client and the rest of Deek's
    backend code

Authentication:
  Two-step OAuth 2.0:
    1. Consent flow at /ebay/oauth/connect → eBay → /ebay/oauth/callback
    2. Authorization code → access_token + refresh_token (stored)
  Refresh:
    Access token is 2-hour. Refresh token is ~18 months with rotation.
    Refresh fires whenever ``within_5_min_of_expiry``.

Scopes:
    Same set as Manufacture today, plus ``sell.marketing`` for
    Promoted Listings reports (the brief's step 5).

Rate limit: eBay's daily call quotas are app-wide; production tier is
generous (5K/day for getOrders) and we're well under.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx


log = logging.getLogger(__name__)


EBAY_OAUTH_URLS: dict[str, dict[str, str]] = {
    'production': {
        'auth':     'https://auth.ebay.com/oauth2/authorize',
        'token':    'https://api.ebay.com/identity/v1/oauth2/token',
        'api_base': 'https://api.ebay.com',
    },
    'sandbox': {
        'auth':     'https://auth.sandbox.ebay.com/oauth2/authorize',
        'token':    'https://api.sandbox.ebay.com/identity/v1/oauth2/token',
        'api_base': 'https://api.sandbox.ebay.com',
    },
}

EBAY_SCOPES: list[str] = [
    'https://api.ebay.com/oauth/api_scope',
    'https://api.ebay.com/oauth/api_scope/sell.inventory',
    'https://api.ebay.com/oauth/api_scope/sell.account',
    'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
    'https://api.ebay.com/oauth/api_scope/sell.marketing',  # Promoted Listings reports
]

REFRESH_BUFFER = timedelta(minutes=5)
HTTP_TIMEOUT = 30.0


def _env() -> str:
    return (os.getenv('EBAY_ENVIRONMENT', 'production') or 'production').lower()


def _client_id() -> str:
    return os.getenv('EBAY_CLIENT_ID', '')


def _client_secret() -> str:
    return os.getenv('EBAY_CLIENT_SECRET', '')


def _ru_name() -> str:
    return os.getenv('EBAY_RU_NAME', '')


def _basic_auth_header() -> str:
    creds = f'{_client_id()}:{_client_secret()}'
    return 'Basic ' + base64.b64encode(creds.encode()).decode('ascii')


def get_authorization_url(state: str) -> str:
    """Build the consent-flow URL Toby visits to grant Deek access."""
    env = _env()
    if not _client_id():
        raise RuntimeError('EBAY_CLIENT_ID not set in env')
    if not _ru_name():
        raise RuntimeError('EBAY_RU_NAME not set — register the redirect URL with eBay first')
    params = {
        'client_id':     _client_id(),
        'response_type': 'code',
        'redirect_uri':  _ru_name(),
        'scope':         ' '.join(EBAY_SCOPES),
        'state':         state,
    }
    return f'{EBAY_OAUTH_URLS[env]["auth"]}?{urlencode(params)}'


async def exchange_code_for_tokens(auth_code: str) -> dict:
    """Convert an authorization code (from the callback) into a
    refresh token + access token, persist to ebay_oauth_tokens."""
    env = _env()
    headers = {
        'Content-Type':  'application/x-www-form-urlencoded',
        'Authorization': _basic_auth_header(),
    }
    data = {
        'grant_type':   'authorization_code',
        'code':         auth_code,
        'redirect_uri': _ru_name(),
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(EBAY_OAUTH_URLS[env]['token'], headers=headers, data=data)
        resp.raise_for_status()
        payload = resp.json()

    access_token = payload['access_token']
    refresh_token = payload['refresh_token']
    expires_in = int(payload.get('expires_in', 7200))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    _save_token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=' '.join(EBAY_SCOPES),
    )
    return {
        'access_token': access_token,
        'expires_at': expires_at.isoformat(),
        'environment': env,
    }


def _save_token(
    *,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
    scopes: str,
) -> None:
    """Upsert the row for the current environment."""
    from .db import get_conn
    env = _env()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ebay_oauth_tokens
                    (environment, access_token, refresh_token, expires_at, scopes,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (environment) DO UPDATE SET
                    access_token  = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    expires_at    = EXCLUDED.expires_at,
                    scopes        = EXCLUDED.scopes,
                    updated_at    = NOW()
                """,
                (env, access_token, refresh_token, expires_at, scopes),
            )
            conn.commit()


def get_status() -> dict:
    """Connection status for the web UI / health checks."""
    from .db import get_conn
    env = _env()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT access_token, refresh_token, expires_at, scopes, updated_at
                     FROM ebay_oauth_tokens WHERE environment = %s""",
                (env,),
            )
            row = cur.fetchone()
    if not row:
        return {
            'connected': False,
            'reason': 'no token — visit /ebay/oauth/connect to consent',
            'environment': env,
        }
    _, _, expires_at, scopes, updated = row
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return {
        'connected':       True,
        'environment':     env,
        'expires_at':      expires_at.isoformat(),
        'expires_in_secs': int((expires_at - datetime.now(timezone.utc)).total_seconds()),
        'scopes':          scopes,
        'updated_at':      updated.isoformat() if updated else None,
    }


class EbayClient:
    """Async eBay REST client with DB-backed token refresh.

    Caller pattern: ``async with EbayClient() as c: await c.get_orders(...)``.
    Each request goes through ``_ensure_access_token`` which refreshes
    the access token if it's within REFRESH_BUFFER of expiry, holding
    a row-level lock so concurrent processes don't race.
    """

    def __init__(self):
        self.environment = _env()
        if not _client_id() or not _client_secret():
            raise RuntimeError(
                'EBAY_CLIENT_ID / EBAY_CLIENT_SECRET must be set'
            )
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @property
    def api_base(self) -> str:
        return EBAY_OAUTH_URLS[self.environment]['api_base']

    async def _ensure_access_token(self) -> str:
        """Return a non-expired access token, refreshing if needed.

        Uses ``SELECT FOR UPDATE`` on the row so when the API server
        and a cron-launched sync hit refresh simultaneously, only one
        actually exchanges the refresh token. The other reads the
        freshly-rotated value.
        """
        from .db import get_conn
        env = self.environment

        # Acquire row lock + read current state in one transaction
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT access_token, refresh_token, expires_at
                      FROM ebay_oauth_tokens
                     WHERE environment = %s
                       FOR UPDATE
                    """,
                    (env,),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(
                        f'No eBay token for env={env}. Run the OAuth '
                        f'consent flow at /ebay/oauth/connect first.'
                    )
                access_token, refresh_token, expires_at = row
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                if datetime.now(timezone.utc) + REFRESH_BUFFER < expires_at:
                    self._access_token = access_token
                    return access_token

                # Refresh — still inside the FOR UPDATE lock so any
                # competing process waits behind this commit.
                log.info('eBay access token near expiry; refreshing')
                new_access, new_refresh, new_expires = await self._refresh(refresh_token)
                cur.execute(
                    """
                    UPDATE ebay_oauth_tokens
                       SET access_token = %s,
                           refresh_token = %s,
                           expires_at    = %s,
                           updated_at    = NOW()
                     WHERE environment = %s
                    """,
                    (new_access, new_refresh, new_expires, env),
                )
                conn.commit()
                self._access_token = new_access
                return new_access

    async def _refresh(self, refresh_token: str) -> tuple[str, str, datetime]:
        """Exchange a refresh token for a new access token. Returns
        (access_token, refresh_token_possibly_rotated, expires_at)."""
        env = self.environment
        headers = {
            'Content-Type':  'application/x-www-form-urlencoded',
            'Authorization': _basic_auth_header(),
        }
        data = {
            'grant_type':    'refresh_token',
            'refresh_token': refresh_token,
            'scope':         ' '.join(EBAY_SCOPES),
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
            resp = await http.post(
                EBAY_OAUTH_URLS[env]['token'], headers=headers, data=data,
            )
            resp.raise_for_status()
            payload = resp.json()
        new_access = payload['access_token']
        # eBay sometimes rotates the refresh token; use the new one if
        # provided, otherwise keep the existing one.
        new_refresh = payload.get('refresh_token', refresh_token)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(payload.get('expires_in', 7200)),
        )
        return new_access, new_refresh, expires_at

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.api_base, timeout=HTTP_TIMEOUT)
        return self._client

    async def _get(self, path: str, params: dict | None = None) -> dict:
        token = await self._ensure_access_token()
        client = await self._http()
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
        }
        resp = await client.get(path, params=params or {}, headers=headers)
        if resp.status_code == 401:
            # Token may have been rotated between _ensure and now; force one retry
            self._access_token = None
            token = await self._ensure_access_token()
            headers['Authorization'] = f'Bearer {token}'
            resp = await client.get(path, params=params or {}, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ── Orders ──────────────────────────────────────────────────────────
    async def get_orders(
        self,
        *,
        creation_date_from: datetime,
        creation_date_to: datetime | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """List orders created in the given window via
        ``GET /sell/fulfillment/v1/order``. eBay's filter syntax is
        ``creationdate:[start..end]``. Paginates server-side.
        """
        if creation_date_to is None:
            creation_date_to = datetime.now(timezone.utc)
        # ISO 8601 format eBay expects — UTC, milliseconds optional
        date_filter = (
            f'creationdate:['
            f'{creation_date_from.strftime("%Y-%m-%dT%H:%M:%S.000Z")}..'
            f'{creation_date_to.strftime("%Y-%m-%dT%H:%M:%S.000Z")}]'
        )
        all_orders: list[dict] = []
        offset = 0
        while True:
            data = await self._get(
                '/sell/fulfillment/v1/order',
                params={
                    'filter': date_filter,
                    'limit':  limit,
                    'offset': offset,
                },
            )
            orders = data.get('orders', [])
            if not orders:
                break
            all_orders.extend(orders)
            total = data.get('total', len(all_orders))
            if len(all_orders) >= total or len(orders) < limit:
                break
            offset += limit
        return all_orders

    # ── Inventory items (minimal mirror) ────────────────────────────────
    async def get_inventory_items(self, *, limit: int = 200) -> list[dict]:
        """List inventory items via the Inventory API. Used to populate
        the minimal ebay_listings mirror — Render still owns the full
        catalogue, this is just (item_id, sku, title) for margin joins.

        eBay's Inventory API uses 'sku' as the primary key (not item_id);
        for sold-on-eBay listings the inventory item is exposed via
        `GET /sell/inventory/v1/inventory_item` with offset/limit
        pagination. The response includes the SKU and product details
        but not the listing's item_id — that's a separate join via
        `GET /sell/inventory/v1/offer?sku=...`. For v1 we accept this
        coupling and call both endpoints.
        """
        all_items: list[dict] = []
        offset = 0
        while True:
            data = await self._get(
                '/sell/inventory/v1/inventory_item',
                params={'limit': limit, 'offset': offset},
            )
            items = data.get('inventoryItems', [])
            if not items:
                break
            all_items.extend(items)
            total = data.get('total', len(all_items))
            if len(all_items) >= total or len(items) < limit:
                break
            offset += limit
        return all_items

    async def get_offers_for_sku(self, sku: str) -> list[dict]:
        """Fetch the offer record(s) for a SKU — gives us listingId
        (item_id in the database)."""
        try:
            data = await self._get(
                '/sell/inventory/v1/offer',
                params={'sku': sku, 'limit': 100},
            )
            return data.get('offers', [])
        except httpx.HTTPStatusError as exc:
            # 404 here means the SKU has no live offers — common for
            # archived inventory items. Treat as empty rather than fail.
            if exc.response.status_code == 404:
                return []
            raise
