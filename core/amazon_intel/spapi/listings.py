"""
Amazon Listings API — read and write listing attributes.

Endpoint: /listings/2021-08-01/items/{sellerId}/{sku}
Method: JSON Patch (RFC 6902) for partial updates.

This is the highest-value capability in the SP-API integration:
it allows Cairn to push content improvements back to Amazon
(prices, titles, bullet points) based on health score recommendations.

Patch operations:
  update_price(sku, price, region) — set new price
  update_bullets(sku, bullets, region) — update bullet points (list of strings)
  update_title(sku, title, region) — update listing title
  bulk_patch(patches, region) — multiple SKUs in one call

All write operations require AMAZON_SELLER_ID_{EU/NA/AU} to be set.
"""
from .client import (
    Region, SELLER_IDS, REGION_MARKETPLACE,
    spapi_get, spapi_patch,
)


def get_listing(sku: str, region: Region = 'EU') -> dict:
    """
    Retrieve current listing attributes for a SKU.
    Returns the full listing dict from SP-API.
    """
    seller_id = SELLER_IDS[region]
    marketplace_id = REGION_MARKETPLACE[region]
    return spapi_get(
        region,
        f'/listings/2021-08-01/items/{seller_id}/{sku}',
        params={
            'marketplaceIds': marketplace_id,
            'includedData': 'attributes,issues,productTypes',
        },
    )


def _patch_listing(sku: str, patch_ops: list[dict], region: Region,
                   product_type: str = 'PRODUCT') -> dict:
    """Apply JSON Patch operations to a listing."""
    seller_id = SELLER_IDS[region]
    marketplace_id = REGION_MARKETPLACE[region]
    body = {
        'productType': product_type,
        'patches': patch_ops,
    }
    return spapi_patch(
        region,
        f'/listings/2021-08-01/items/{seller_id}/{sku}',
        body=body,
        params={'marketplaceIds': marketplace_id},
    )


def update_price(sku: str, price: float, currency: str = 'GBP',
                 region: Region = 'EU') -> dict:
    """Set the listing price for a SKU."""
    patch_ops = [{
        'op': 'replace',
        'path': '/attributes/purchasable_offer',
        'value': [{
            'marketplace_id': REGION_MARKETPLACE[region],
            'currency': currency,
            'our_price': [{'schedule': [{'value_with_tax': price}]}],
        }],
    }]
    return _patch_listing(sku, patch_ops, region)


def update_bullets(sku: str, bullets: list[str], region: Region = 'EU') -> dict:
    """
    Replace all bullet points for a SKU.
    bullets: list of up to 5 strings.
    """
    bullets = bullets[:5]
    patch_ops = [{
        'op': 'replace',
        'path': '/attributes/bullet_point',
        'value': [{'value': b, 'marketplace_id': REGION_MARKETPLACE[region]}
                  for b in bullets if b],
    }]
    return _patch_listing(sku, patch_ops, region)


def update_title(sku: str, title: str, region: Region = 'EU') -> dict:
    """Update the listing title for a SKU."""
    patch_ops = [{
        'op': 'replace',
        'path': '/attributes/item_name',
        'value': [{'value': title, 'marketplace_id': REGION_MARKETPLACE[region]}],
    }]
    return _patch_listing(sku, patch_ops, region)


def update_keywords(sku: str, keywords: list[str], region: Region = 'EU') -> dict:
    """
    Replace generic keywords for a SKU.
    keywords: list of up to 5 keyword strings.
    """
    keywords = keywords[:5]
    patch_ops = [{
        'op': 'replace',
        'path': '/attributes/generic_keyword',
        'value': [{'value': k, 'marketplace_id': REGION_MARKETPLACE[region]}
                  for k in keywords if k],
    }]
    return _patch_listing(sku, patch_ops, region)


def bulk_patch_listings(patches: list[dict], region: Region = 'EU') -> list[dict]:
    """
    Apply patches to multiple SKUs.

    patches: list of dicts, each with:
      {
        'sku': 'M0001UK',
        'ops': [{'op': 'replace', 'path': '/attributes/...', 'value': ...}],
        'product_type': 'PRODUCT',  # optional
      }

    Returns list of results (one per SKU).
    """
    results = []
    for p in patches:
        try:
            result = _patch_listing(
                p['sku'], p['ops'], region,
                product_type=p.get('product_type', 'PRODUCT'),
            )
            results.append({'sku': p['sku'], 'status': 'ok', 'result': result})
        except Exception as e:
            results.append({'sku': p['sku'], 'status': 'error', 'error': str(e)})
    return results
