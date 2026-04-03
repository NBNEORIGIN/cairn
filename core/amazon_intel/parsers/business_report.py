"""
Amazon Business Report CSV parser.

Source: Seller Central → Reports → Business Reports → By ASIN →
        Detail Page Sales and Traffic

Format: CSV with header row.
Amazon sometimes changes header names slightly between downloads,
so we use a fuzzy header alias map.
"""
import csv
import io
from core.amazon_intel.db import get_conn, insert_upload, update_upload


# Map expected column names to our internal field names.
# Multiple aliases per field handle Amazon's header variations.
HEADER_ALIASES = {
    'parent_asin': [
        '(Parent) ASIN', 'Parent ASIN', 'parent asin',
    ],
    'child_asin': [
        '(Child) ASIN', 'Child ASIN', 'child asin', 'ASIN',
    ],
    'title': [
        'Title', 'title',
    ],
    'sessions': [
        'Sessions - Total', 'Sessions — Total', 'Sessions',
        'Sessions - Mobile', 'Total Sessions',
    ],
    'session_percentage': [
        'Session Percentage - Total', 'Session Percentage — Total',
        'Session Percentage', 'Session %',
    ],
    'page_views': [
        'Page Views - Total', 'Page Views — Total', 'Page Views',
        'Total Page Views',
    ],
    'buy_box_percentage': [
        'Buy Box Percentage', 'Buy Box %', 'Featured Offer (Buy Box) Percentage',
    ],
    'units_ordered': [
        'Units Ordered', 'Units Ordered - Total',
    ],
    'unit_session_percentage': [
        'Unit Session Percentage', 'Unit Session Percentage - Total',
        'Unit Session %', 'Conversion Rate',
    ],
    'ordered_product_sales': [
        'Ordered Product Sales', 'Ordered Product Sales - Total',
    ],
    'total_order_items': [
        'Total Order Items', 'Total Order Items - Total',
    ],
}


def _build_column_map(headers: list[str]) -> dict[str, int]:
    """Map our internal field names to column indices using aliases."""
    col_map = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            for i, h in enumerate(headers):
                if h.strip().lower() == alias.lower():
                    col_map[field] = i
                    break
            if field in col_map:
                break
    return col_map


def _clean_numeric(val: str, is_pct: bool = False) -> float | None:
    """Parse a numeric value, handling commas, currency symbols, and percentages."""
    if not val or val.strip() in ('', '--', 'N/A'):
        return None
    val = val.strip().replace(',', '').replace('£', '').replace('$', '').replace('%', '')
    try:
        result = float(val)
        if is_pct and result > 1:
            result = result / 100.0
        return result
    except (ValueError, TypeError):
        return None


def _clean_int(val: str) -> int:
    if not val or val.strip() in ('', '--', 'N/A'):
        return 0
    val = val.strip().replace(',', '')
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def parse_business_report(content: bytes, filename: str) -> list[dict]:
    """Parse a business report CSV. Returns list of row dicts."""
    # Try UTF-8 then latin-1
    for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode {filename}")

    reader = csv.reader(io.StringIO(text))
    headers = next(reader)
    col_map = _build_column_map(headers)

    if 'child_asin' not in col_map:
        raise ValueError(
            f"Cannot find ASIN column in headers: {headers[:15]}. "
            f"Expected one of: {HEADER_ALIASES['child_asin']}"
        )

    rows = []
    for line in reader:
        if not line or all(not c.strip() for c in line):
            continue

        def _get(field: str) -> str:
            idx = col_map.get(field)
            if idx is None or idx >= len(line):
                return ''
            return line[idx].strip()

        child_asin = _get('child_asin')
        if not child_asin:
            continue

        rows.append({
            'parent_asin': _get('parent_asin') or None,
            'child_asin': child_asin,
            'title': _get('title') or None,
            'sessions': _clean_int(_get('sessions')),
            'session_percentage': _clean_numeric(_get('session_percentage'), is_pct=True),
            'page_views': _clean_int(_get('page_views')),
            'buy_box_percentage': _clean_numeric(_get('buy_box_percentage'), is_pct=True),
            'units_ordered': _clean_int(_get('units_ordered')),
            'unit_session_percentage': _clean_numeric(_get('unit_session_percentage'), is_pct=True),
            'ordered_product_sales': _clean_numeric(_get('ordered_product_sales')),
            'total_order_items': _clean_int(_get('total_order_items')),
        })

    return rows


def parse_and_store_business_report(content: bytes, filename: str,
                                     marketplace: str = None) -> dict:
    """Parse and store a business report. Returns summary."""
    upload_id = insert_upload(filename, 'business_report', marketplace)

    try:
        rows = parse_business_report(content, filename)
    except Exception as e:
        update_upload(upload_id, error_count=1, errors=[str(e)], status='error')
        raise

    errors = []
    stored = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                try:
                    cur.execute(
                        """INSERT INTO ami_business_report_data
                               (upload_id, parent_asin, child_asin, title,
                                sessions, session_percentage, page_views,
                                buy_box_percentage, units_ordered,
                                unit_session_percentage, ordered_product_sales,
                                total_order_items)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (upload_id, row['parent_asin'], row['child_asin'],
                         row['title'], row['sessions'], row['session_percentage'],
                         row['page_views'], row['buy_box_percentage'],
                         row['units_ordered'], row['unit_session_percentage'],
                         row['ordered_product_sales'], row['total_order_items']),
                    )
                    stored += 1
                except Exception as e:
                    errors.append(f"ASIN {row['child_asin']}: {e}")

            conn.commit()

    update_upload(upload_id, row_count=stored, skip_count=len(rows) - stored,
                  error_count=len(errors), errors=errors[:50])

    return {
        'upload_id': upload_id,
        'filename': filename,
        'file_type': 'business_report',
        'row_count': stored,
        'skip_count': len(rows) - stored,
        'error_count': len(errors),
        'errors': errors[:10],
        'status': 'complete',
    }
