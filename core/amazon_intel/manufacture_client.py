"""
HTTP client for Manufacture API — fetches product/margin data by M-number.

Per CLAUDE.md: "Never access another module's database directly."
All Manufacture data comes through its DRF API at port 8002.
"""
import os
import httpx
from typing import Optional


MANUFACTURE_API_URL = os.getenv('MANUFACTURE_API_URL', 'https://manufacture.nbnesigns.co.uk')
MANUFACTURE_API_KEY = os.getenv('CAIRN_API_KEY', '') or os.getenv('MANUFACTURE_API_KEY', '')


def _auth_headers() -> dict:
    """Bearer token for server-to-server calls to Manufacture (cost endpoints)."""
    if MANUFACTURE_API_KEY:
        return {'Authorization': f'Bearer {MANUFACTURE_API_KEY}'}
    return {}


async def get_product_by_m_number(m_number: str) -> Optional[dict]:
    """Fetch a product from Manufacture's DRF API by M-number."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f'{MANUFACTURE_API_URL}/api/products/',
                params={'search': m_number},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get('results', data) if isinstance(data, dict) else data
            if not results:
                return None
            # Search returns a list — find exact match
            for p in results:
                if p.get('m_number') == m_number:
                    return p
            return results[0] if results else None
    except (httpx.ConnectError, httpx.TimeoutException):
        return None


async def get_stock_level(m_number: str) -> Optional[dict]:
    """Fetch stock level data from Manufacture's API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f'{MANUFACTURE_API_URL}/api/stock/',
                params={'search': m_number},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get('results', data) if isinstance(data, dict) else data
            return results[0] if results else None
    except (httpx.ConnectError, httpx.TimeoutException):
        return None


async def is_available() -> bool:
    """Quick connectivity check — returns False if Manufacture API is unreachable."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f'{MANUFACTURE_API_URL}/api/products/', params={'limit': 1})
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


async def batch_product_data(m_numbers: list[str]) -> dict[str, dict]:
    """
    Fetch product + stock data for many M-numbers.
    Returns dict keyed by M-number with combined product+stock info.
    Gracefully handles Manufacture being offline (returns empty dict).
    """
    import asyncio

    # Quick connectivity check before attempting batch
    if not await is_available():
        return {}

    result = {}
    sem = asyncio.Semaphore(5)  # limit concurrent requests

    async def _fetch_one(m: str):
        async with sem:
            product = await get_product_by_m_number(m)
            if not product:
                return
            stock = await get_stock_level(m)
            result[m] = {
                'description': product.get('description', ''),
                'blank': product.get('blank', ''),
                'material': product.get('material', ''),
                'cost_price': None,  # not yet exposed by Manufacture API
                'current_stock': stock.get('current_stock') if stock else None,
                'thirty_day_sales': stock.get('thirty_day_sales') if stock else None,
                'sixty_day_sales': stock.get('sixty_day_sales') if stock else None,
            }

    tasks = [_fetch_one(m) for m in set(m_numbers) if m]
    await asyncio.gather(*tasks, return_exceptions=True)
    return result


async def get_costs_bulk(m_numbers: list[str] | None = None) -> tuple[dict[str, dict], dict]:
    """
    Fetch Manufacture cost breakdown for many M-numbers in a single call.

    Uses GET /api/costs/price/bulk/ (Bearer-auth). Returns a tuple of:
      (costs_by_m_number, overhead_context)

    costs_by_m_number: dict keyed by M-number with cost breakdown
    overhead_context: dict with monthly_overhead_gbp, b2b/ebay revenue, etc.

    Returns (empty dict, empty dict) if the API is unreachable.
    """
    params: dict = {}
    if m_numbers:
        # Keep URL length reasonable — cap at ~2000 M-numbers per call.
        params['m_numbers'] = ','.join(sorted({m for m in m_numbers if m})[:2000])
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f'{MANUFACTURE_API_URL}/api/costs/price/bulk/',
                params=params,
                headers=_auth_headers(),
            )
            if resp.status_code != 200:
                return {}, {}
            data = resp.json() or {}
            results = data.get('results') or []
            overhead_ctx = data.get('overhead_context') or {}
            return (
                {r['m_number']: r for r in results if r.get('m_number')},
                overhead_ctx,
            )
    except (httpx.ConnectError, httpx.TimeoutException):
        return {}, {}
