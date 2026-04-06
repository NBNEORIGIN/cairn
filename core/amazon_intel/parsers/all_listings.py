"""
Amazon All Listings Report parser.

Source: Seller Central → Inventory → Inventory Reports → All Listings Report
         (also labelled "Active Listings Report" in some Seller Central versions)
Format: TSV (tab-delimited text file)

This is the key lookup table — every active listing with its seller-sku
mapped to asin1. It bridges the gap between flatfile SKUs (which often
lack ASINs) and business report ASINs.

Key columns:
  seller-sku          — the SKU used in flatfiles and the stock sheet
  asin1               — the primary ASIN for this listing
  product-id          — usually same as asin1
  item-name           — listing title
  price               — current price
  open-date           — listing creation date (DD/MM/YYYY HH:MM:SS GMT/BST)
  fulfillment-channel — DEFAULT (MFN) or AMAZON_NA/AMAZON_EU (FBA)
  status              — Active, Inactive, etc.
"""
import csv
import io
import re
from datetime import datetime, timezone, timedelta
from core.amazon_intel.db import get_conn, insert_upload, update_upload


def _parse_open_date(val: str | None) -> str | None:
    """
    Parse Amazon's open-date format into ISO timestamp string.
    Handles: '19/03/2021 13:39:42 GMT', '15/04/2021 13:17:19 BST'
    BST = UTC+1, GMT = UTC+0. Returns UTC string without tzinfo for DB storage.
    """
    if not val:
        return None
    val = val.strip()
    # Split off timezone suffix (GMT/BST/UTC)
    tz_offset = timedelta(0)
    for suffix, offset_hours in [('BST', 1), ('GMT', 0), ('UTC', 0)]:
        if val.upper().endswith(suffix):
            val = val[:-len(suffix)].strip()
            tz_offset = timedelta(hours=offset_hours)
            break
    try:
        dt = datetime.strptime(val, '%d/%m/%Y %H:%M:%S')
        # Adjust to UTC
        dt_utc = dt - tz_offset
        return dt_utc.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        pass
    # Try ISO format as fallback
    try:
        return datetime.fromisoformat(val.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return None


def parse_all_listings_report(content: bytes, filename: str) -> list[dict]:
    """Parse the All Listings Report TSV. Returns list of row dicts."""
    for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode {filename}")

    reader = csv.DictReader(io.StringIO(text), delimiter='\t')
    rows = []

    for line in reader:
        sku = (line.get('seller-sku') or '').strip()
        if not sku:
            continue

        asin = (line.get('asin1') or '').strip()
        product_id = (line.get('product-id') or '').strip()
        # Prefer asin1, fall back to product-id if it looks like an ASIN
        if not asin and re.match(r'^B[0-9A-Z]{9}$', product_id):
            asin = product_id

        rows.append({
            'sku': sku,
            'asin': asin or None,
            'title': (line.get('item-name') or '').strip() or None,
            'price': _parse_price(line.get('price')),
            'status': (line.get('status') or '').strip() or None,
            'fulfillment_channel': (line.get('fulfillment-channel') or '').strip() or None,
            'listing_created_at': _parse_open_date(line.get('open-date')),
        })

    return rows


def _parse_price(val: str | None) -> float | None:
    if not val:
        return None
    val = val.strip().replace(',', '').replace('£', '').replace('$', '')
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def parse_and_store_all_listings(content: bytes, filename: str,
                                  marketplace: str = None) -> dict:
    """
    Parse All Listings Report and enrich ami_sku_mapping with SKU→ASIN links.
    Also updates ami_flatfile_data with ASINs where missing.
    """
    upload_id = insert_upload(filename, 'all_listings', marketplace)

    try:
        rows = parse_all_listings_report(content, filename)
    except Exception as e:
        update_upload(upload_id, error_count=1, errors=[str(e)], status='error')
        raise

    mapping_inserted = 0
    mapping_updated = 0
    flatfile_enriched = 0
    errors = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                if not row['asin']:
                    continue

                # Upsert into ami_sku_mapping
                try:
                    cur.execute(
                        """INSERT INTO ami_sku_mapping (sku, m_number, asin, source)
                           VALUES (%s, %s, %s, 'all_listings')
                           ON CONFLICT (sku) DO UPDATE SET
                               asin = COALESCE(EXCLUDED.asin, ami_sku_mapping.asin),
                               updated_at = NOW()
                           RETURNING (xmax = 0) AS is_insert""",
                        (row['sku'], _extract_m_number(row['sku']) or row['sku'],
                         row['asin']),
                    )
                    result = cur.fetchone()
                    if result and result[0]:
                        mapping_inserted += 1
                    else:
                        mapping_updated += 1
                except Exception as e:
                    errors.append(f"Mapping {row['sku']}: {e}")
                    conn.rollback()
                    continue

                # Update flatfile data: enrich ASIN and listing_created_at
                cur.execute(
                    """UPDATE ami_flatfile_data
                       SET asin = %s,
                           listing_created_at = COALESCE(listing_created_at, %s)
                       WHERE sku = %s AND (asin IS NULL OR asin = '')""",
                    (row['asin'], row.get('listing_created_at'), row['sku']),
                )
                flatfile_enriched += cur.rowcount

                # Also fill listing_created_at on rows that already have ASIN
                if row.get('listing_created_at'):
                    cur.execute(
                        """UPDATE ami_flatfile_data
                           SET listing_created_at = %s
                           WHERE sku = %s AND listing_created_at IS NULL""",
                        (row['listing_created_at'], row['sku']),
                    )

            conn.commit()

    update_upload(upload_id, row_count=len(rows),
                  skip_count=sum(1 for r in rows if not r['asin']),
                  error_count=len(errors), errors=errors[:50])

    return {
        'upload_id': upload_id,
        'filename': filename,
        'file_type': 'all_listings',
        'total_rows': len(rows),
        'with_asin': sum(1 for r in rows if r['asin']),
        'mapping_inserted': mapping_inserted,
        'mapping_updated': mapping_updated,
        'flatfile_asins_enriched': flatfile_enriched,
        'error_count': len(errors),
        'errors': errors[:10],
        'status': 'complete',
    }


def _extract_m_number(sku: str) -> str | None:
    """Extract M-number from SKU if present."""
    match = re.match(r'^(M\d{4})', sku)
    if match:
        return match.group(1)
    return None
