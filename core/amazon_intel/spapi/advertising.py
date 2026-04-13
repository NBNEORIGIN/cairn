"""
Amazon Advertising API integration.

Separate from SP-API — different base URL, different auth scope.
Uses the same LWA access token but requires:
  - Amazon-Advertising-API-ClientId header
  - Amazon-Advertising-API-Scope: {profile_id} header

Profile discovery: GET /v2/profiles — returns all ad profiles linked to the app.
Run /ami/spapi/advertising/profiles once to discover profile IDs.

Advertising report flow (Ads API v3):
  POST /reporting/reports → reportId
  GET  /reporting/reports/{reportId} → poll until SUCCESS
  GET  report URL (presigned S3) → download gzip → parse CSV

Reference: https://advertising.amazon.com/API/docs/en-us/reporting/v3/overview
"""
import gzip
import io
import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx

from .client import Region, CLIENT_ID, get_access_token

ADS_REGION_HOSTS: dict[str, str] = {
    'EU': 'advertising.amazon.co.uk',
    'NA': 'advertising.amazon.com',
    'FE': 'advertising.amazon.com.au',
}

# Set via /ami/spapi/advertising/profiles discovery
# Can also be set directly in .env
ADS_PROFILE_IDS: dict[str, str] = {
    'EU': os.getenv('AMAZON_ADS_PROFILE_ID_EU', ''),
    'NA': os.getenv('AMAZON_ADS_PROFILE_ID_NA', ''),
    'FE': os.getenv('AMAZON_ADS_PROFILE_ID_AU', ''),
}


def _ads_headers(region: Region, profile_id: str | None = None) -> dict[str, str]:
    token = get_access_token(region)
    pid = profile_id or ADS_PROFILE_IDS.get(region, '')
    headers = {
        'Authorization': f'Bearer {token}',
        'Amazon-Advertising-API-ClientId': CLIENT_ID,
        'Content-Type': 'application/json',
    }
    if pid:
        headers['Amazon-Advertising-API-Scope'] = pid
    return headers


def get_advertising_profiles(region: Region = 'EU') -> list[dict]:
    """
    Discover all advertising profiles linked to this app for a region.
    Store the returned profileId values in .env as AMAZON_ADS_PROFILE_ID_*.

    Uses Ads API v3 endpoint (v2 /profiles was deprecated and returns 301).
    v3: GET /v3/profiles with apiProgram filter for Sponsored Products.
    """
    host = ADS_REGION_HOSTS[region]
    headers = _ads_headers(region)
    headers['Accept'] = 'application/vnd.amazonadvertising.v3+json'

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(
            f'https://{host}/v3/profiles',
            params={'apiProgram': 'SPONSORED_PRODUCTS'},
            headers=headers,
        )
        resp.raise_for_status()

    profiles = resp.json().get('profiles', resp.json()) if isinstance(resp.json(), dict) else resp.json()
    if not isinstance(profiles, list):
        profiles = [profiles] if profiles else []

    return [
        {
            'profile_id': str(p.get('profileId', '')),
            'marketplace_id': p.get('accountInfo', {}).get('marketplaceStringId', ''),
            'account_id': p.get('accountInfo', {}).get('id', ''),
            'account_name': p.get('accountInfo', {}).get('name', ''),
            'account_type': p.get('accountInfo', {}).get('type', ''),
            'timezone': p.get('timezone', ''),
            'currency_code': p.get('currencyCode', ''),
        }
        for p in profiles
    ]


def request_sponsored_products_report(region: Region, profile_id: str,
                                       days: int = 30) -> str:
    """
    Request a Sponsored Products search term report (Ads API v3).
    Returns reportId.
    """
    host = ADS_REGION_HOSTS[region]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    body = {
        'name': f'SP Search Term Report {start.strftime("%Y-%m-%d")} to {end.strftime("%Y-%m-%d")}',
        'startDate': start.strftime('%Y-%m-%d'),
        'endDate': end.strftime('%Y-%m-%d'),
        'configuration': {
            'adProduct': 'SPONSORED_PRODUCTS',
            'groupBy': ['searchTerm'],
            'columns': [
                'campaignName', 'adGroupName', 'targetingExpression', 'matchType',
                'query', 'impressions', 'clicks', 'cost', 'purchases7d',
                'sales7d', 'advertisedAsin', 'advertisedSku',
            ],
            'reportTypeId': 'spSearchTerm',
            'timeUnit': 'SUMMARY',
            'format': 'GZIP_JSON',
        },
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f'https://{host}/reporting/reports',
            json=body,
            headers=_ads_headers(region, profile_id),
        )
        resp.raise_for_status()

    return resp.json()['reportId']


def wait_for_ads_report(region: Region, profile_id: str, report_id: str,
                        max_wait: int = 1800, poll_interval: int = 30) -> str:
    """Poll Ads API until report is SUCCESS. Returns download URL."""
    host = ADS_REGION_HOSTS[region]
    deadline = time.time() + max_wait
    while time.time() < deadline:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f'https://{host}/reporting/reports/{report_id}',
                headers=_ads_headers(region, profile_id),
            )
            resp.raise_for_status()

        data = resp.json()
        status = data.get('status', '')
        if status == 'COMPLETED':
            return data['url']
        if status in ('FAILED', 'CANCELLED'):
            raise RuntimeError(f"Ads report {report_id} failed: {status}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Ads report {report_id} not ready after {max_wait}s")


def download_ads_report(url: str) -> list[dict]:
    """Download and parse GZIP_JSON ads report. Returns list of row dicts."""
    with httpx.Client(timeout=120) as client:
        resp = client.get(url)
        resp.raise_for_status()

    content = gzip.decompress(resp.content)
    return json.loads(content.decode('utf-8'))


def _parse_ads_rows(raw_rows: list[dict]) -> list[dict]:
    """Normalise Ads API v3 JSON rows to ami_advertising_data shape."""
    rows = []
    for r in raw_rows:
        spend = r.get('cost') or r.get('spend') or 0
        sales = r.get('sales7d') or r.get('salesOtherSku7d') or 0
        orders = r.get('purchases7d') or r.get('orders7d') or 0

        try:
            acos = round(float(spend) / float(sales), 4) if float(sales) > 0 else None
        except (TypeError, ValueError, ZeroDivisionError):
            acos = None

        try:
            roas = round(float(sales) / float(spend), 4) if float(spend) > 0 else None
        except (TypeError, ValueError, ZeroDivisionError):
            roas = None

        rows.append({
            'report_type': 'sp_search_term',
            'campaign_name': (r.get('campaignName') or '')[:500],
            'ad_group_name': (r.get('adGroupName') or '')[:500],
            'asin': (r.get('advertisedAsin') or '')[:20] or None,
            'sku': (r.get('advertisedSku') or '')[:100] or None,
            'targeting': (r.get('targetingExpression') or '')[:500],
            'match_type': (r.get('matchType') or '')[:30],
            'customer_search_term': (r.get('query') or '')[:500],
            'impressions': int(r.get('impressions') or 0),
            'clicks': int(r.get('clicks') or 0),
            'spend': round(float(spend), 2),
            'sales_7d': round(float(sales), 2),
            'orders_7d': int(orders),
            'acos': acos,
            'roas': roas,
        })
    return rows


def sync_advertising(region: Region = 'EU', profile_id: str | None = None,
                     days: int = 30) -> dict:
    """
    Pull Sponsored Products search term report, parse, store.
    profile_id defaults to AMAZON_ADS_PROFILE_ID_{region} from .env.
    """
    from core.amazon_intel.db import get_conn, insert_upload, update_upload

    pid = profile_id or ADS_PROFILE_IDS.get(region, '')
    if not pid:
        raise ValueError(
            f"No advertising profile ID for region {region}. "
            f"Run GET /ami/spapi/advertising/profiles to discover, "
            f"then set AMAZON_ADS_PROFILE_ID_{region} in .env"
        )

    report_id = request_sponsored_products_report(region, pid, days=days)
    url = wait_for_ads_report(region, pid, report_id)
    raw_rows = download_ads_report(url)
    rows = _parse_ads_rows(raw_rows)

    marketplace_map = {'EU': 'UK', 'NA': 'US', 'FE': 'AU'}
    marketplace = marketplace_map.get(region, region)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    filename = f'spapi_ads_sp_{region}_{ts}.json'
    upload_id = insert_upload(filename, 'advertising', marketplace)

    errors: list[str] = []
    stored = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                try:
                    cur.execute(
                        """INSERT INTO ami_advertising_data
                               (upload_id, report_type, campaign_name, ad_group_name,
                                asin, sku, targeting, match_type,
                                customer_search_term, impressions, clicks,
                                spend, sales_7d, orders_7d, acos, roas)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (upload_id, row['report_type'], row['campaign_name'],
                         row['ad_group_name'], row['asin'], row['sku'],
                         row['targeting'], row['match_type'],
                         row['customer_search_term'], row['impressions'],
                         row['clicks'], row['spend'], row['sales_7d'],
                         row['orders_7d'], row['acos'], row['roas']),
                    )
                    stored += 1
                except Exception as e:
                    errors.append(str(e)[:200])
            conn.commit()

    update_upload(upload_id, row_count=stored, skip_count=len(rows) - stored,
                  error_count=len(errors), errors=errors[:50])

    return {
        'upload_id': upload_id,
        'region': region,
        'source': 'spapi',
        'row_count': stored,
        'error_count': len(errors),
        'errors': errors[:10],
        'status': 'complete',
    }
