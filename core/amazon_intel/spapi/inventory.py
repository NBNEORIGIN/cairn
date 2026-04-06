"""
Inventory sync via SP-API.

Replaces: manual All Listings Report upload (Seller Central → Inventory Reports)

Report: GET_MERCHANT_LISTINGS_ALL_DATA
Format: TSV — same column structure as manual All Listings Report.
Reuses existing parse_and_store_all_listings() — no duplicate parsing logic.

Regions: EU (UK), NA (US), FE (AU)
"""
from datetime import datetime, timezone
from .client import Region, REGION_MARKETPLACE_CODE, run_report


def sync_inventory(region: Region = 'EU') -> dict:
    """
    Pull All Listings Report for a region, parse, and store.

    Uses the existing all_listings parser — output goes into:
      - ami_sku_mapping (SKU → ASIN)
      - ami_flatfile_data (listing_created_at enrichment)

    Returns the summary dict from parse_and_store_all_listings.
    """
    from core.amazon_intel.parsers.all_listings import parse_and_store_all_listings

    content = run_report(region, 'GET_MERCHANT_LISTINGS_ALL_DATA')

    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    filename = f'spapi_all_listings_{region}_{ts}.txt'
    marketplace = REGION_MARKETPLACE_CODE.get(region, region)

    result = parse_and_store_all_listings(content, filename, marketplace=marketplace)
    result['region'] = region
    result['source'] = 'spapi'
    return result
