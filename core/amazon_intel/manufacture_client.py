"""
HTTP client for Manufacture API — fetches product/margin data by M-number.

Per CLAUDE.md: "Never access another module's database directly."
All Manufacture data comes through its DRF API at port 8002.
"""
import os
import httpx
from typing import Optional


MANUFACTURE_API_URL = os.getenv('MANUFACTURE_API_URL', 'http://localhost:8002')


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


async def batch_product_data(m_numbers: list[str]) -> dict[str, dict]:
    """
    Fetch product + stock data for many M-numbers.
    Returns dict keyed by M-number with combined product+stock info.
    Gracefully handles Manufacture being offline (returns empty dict).
    """
    import asyncio

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
