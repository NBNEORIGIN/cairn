"""
Stock sheet CSV parser — seeds ami_sku_mapping from the canonical
Shipment_Stock_Sheet_-_ASSEMBLY.csv file.

The CSV has duplicated headers (a second lookup block starts at col 12),
so we use positional access, NOT DictReader.

Columns:
  0: SKU           (marketplace-specific, e.g. OD001209SilverUK)
  1: MASTER SKU    (M-number, e.g. M0001) — populated on every row
  2: NEW SKU       (secondary numeric ID, e.g. 2796)
  3: COUNTRY       (UK, US, CA, AU, DE, ETSY, EBAY, FR CRAFTS, etc.)
  4: DESCRIPTION   (product description)
  5: BLANK         (substrate name: DONALD, SAVILLE, DICK, etc.)
  6: IS PERSONALISED?  (empty or truthy)
  7: ASIN          (Amazon ASIN — populated for ~1,162 entries)
"""
import csv
import os
from pathlib import Path
from core.amazon_intel.db import get_conn


STOCK_SHEET_PATH = os.getenv(
    'STOCK_SHEET_PATH',
    'D:/manufacture/data/Shipment Stock Sheet - ASSEMBLY.csv',
)

# Normalise country codes from the stock sheet's inconsistent values
COUNTRY_MAP = {
    'uk': 'UK', 'usa': 'US', 'us': 'US', 'ca': 'CA', 'canada': 'CA',
    'au': 'AU', 'aus': 'AU', 'de': 'DE', 'germany': 'DE',
    'fr': 'FR', 'fr crafts': 'FR', 'ebay': 'EBAY', 'etsy': 'ETSY',
    'amazon': 'UK',  # bare "amazon" means UK marketplace
}


def _normalise_country(raw: str) -> str:
    if not raw:
        return ''
    return COUNTRY_MAP.get(raw.strip().lower(), raw.strip().upper())


def _parse_stock_sheet(csv_path: str) -> list[dict]:
    """Parse the CSV using positional column access. Returns list of mapping dicts."""
    rows = []
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Stock sheet not found: {csv_path}")

    # Try UTF-8 first, fall back to latin-1
    for encoding in ('utf-8', 'latin-1'):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode {csv_path}")

    reader = csv.reader(text.splitlines())
    header = next(reader)  # skip header row

    for line_num, cols in enumerate(reader, start=2):
        if len(cols) < 8:
            continue

        sku = (cols[0] or '').strip()
        m_number = (cols[1] or '').strip()

        if not sku or not m_number:
            continue
        if m_number.lower() in ('not found', ''):
            continue

        new_sku = (cols[2] or '').strip()
        country = _normalise_country(cols[3])
        description = (cols[4] or '').strip()
        blank_name = (cols[5] or '').strip()
        is_personalised = bool((cols[6] or '').strip())
        asin = (cols[7] or '').strip() if len(cols) > 7 else ''

        rows.append({
            'sku': sku,
            'm_number': m_number,
            'new_sku': new_sku or None,
            'country': country or None,
            'description': description or None,
            'blank_name': blank_name or None,
            'is_personalised': is_personalised,
            'asin': asin or None,
        })

    return rows


def sync_from_stock_sheet(csv_path: str = None) -> dict:
    """
    Parse the stock sheet and upsert all rows into ami_sku_mapping.
    Returns summary stats.
    """
    path = csv_path or STOCK_SHEET_PATH
    rows = _parse_stock_sheet(path)

    inserted = 0
    updated = 0
    skipped = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                # Upsert on sku (unique index)
                cur.execute(
                    """INSERT INTO ami_sku_mapping
                           (sku, m_number, new_sku, country, description,
                            blank_name, is_personalised, asin, source)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'stock_sheet')
                       ON CONFLICT (sku) DO UPDATE SET
                           m_number = EXCLUDED.m_number,
                           new_sku = COALESCE(EXCLUDED.new_sku, ami_sku_mapping.new_sku),
                           country = COALESCE(EXCLUDED.country, ami_sku_mapping.country),
                           description = COALESCE(EXCLUDED.description, ami_sku_mapping.description),
                           blank_name = COALESCE(EXCLUDED.blank_name, ami_sku_mapping.blank_name),
                           is_personalised = EXCLUDED.is_personalised,
                           asin = COALESCE(EXCLUDED.asin, ami_sku_mapping.asin),
                           updated_at = NOW()
                       RETURNING (xmax = 0) AS is_insert""",
                    (row['sku'], row['m_number'], row['new_sku'], row['country'],
                     row['description'], row['blank_name'], row['is_personalised'],
                     row['asin']),
                )
                result = cur.fetchone()
                if result and result[0]:
                    inserted += 1
                else:
                    updated += 1

            conn.commit()

    return {
        'source': path,
        'total_rows': len(rows),
        'inserted': inserted,
        'updated': updated,
        'skipped': skipped,
    }


def get_mapping_stats() -> dict:
    """Return mapping table statistics."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ami_sku_mapping")
            total = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT m_number) FROM ami_sku_mapping")
            m_numbers = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT asin) FROM ami_sku_mapping WHERE asin IS NOT NULL")
            asins = cur.fetchone()[0]

            cur.execute(
                """SELECT country, COUNT(*) FROM ami_sku_mapping
                   WHERE country IS NOT NULL
                   GROUP BY country ORDER BY COUNT(*) DESC"""
            )
            by_country = {row[0]: row[1] for row in cur.fetchall()}

    return {
        'total_skus': total,
        'unique_m_numbers': m_numbers,
        'unique_asins': asins,
        'by_country': by_country,
    }


def lookup_m_number(sku: str) -> str | None:
    """Look up the M-number for a given SKU."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT m_number FROM ami_sku_mapping WHERE sku = %s",
                (sku,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def lookup_by_asin(asin: str) -> list[dict]:
    """Look up all SKU mappings for a given ASIN."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT sku, m_number, country, blank_name
                   FROM ami_sku_mapping WHERE asin = %s""",
                (asin,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
