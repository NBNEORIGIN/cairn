"""
Re-seed ami_sku_mapping from the canonical Shipment Stock Sheet CSV.

This is the source-of-truth file for every (SKU, channel/country, M-number)
mapping NBNE publishes across Amazon UK/US/CA/AU/DE/IT/NL/FR/ES, eBay,
Etsy, Shopify, and the FR/IT splits between NBNE (OriginDesigned) and
NorthByNorthEast (Origin Crafts) seller accounts.

Strategy:

    1. Schema: change UNIQUE (sku) → UNIQUE (sku, country). The current
       constraint is wrong — the same SKU legitimately appears under
       multiple channels (e.g. OD001061 on UK, EBAY, ETSY). The previous
       seeder silently dropped collisions, losing data.

    2. Snapshot the existing table to ami_sku_mapping_backup_<timestamp>
       so we can roll back / diff against the old contents.

    3. TRUNCATE + bulk INSERT from the CSV with normalisation and skip
       rules (see _normalise_country and _SKIP_COUNTRY_VALUES).

    4. Print before / after / per-channel diff for sanity-check.

The CSV is positional (not name-keyed) — col 0 is SKU, col 1 is M_NUMBER,
col 2 NEW_SKU, col 3 COUNTRY, col 4 DESCRIPTION, col 5 BLANK,
col 6 IS_PERSONALISED, col 7 ASIN. Columns 11-21 are a spreadsheet-side
lookup helper, not real data — ignored.

The FR CRAFTS / FR DESIGNED / IT DESIGNED variants and their *DUPLICATE*
flags are PRESERVED IN-PLACE in the country column. The forthcoming
multi-account ingestion brief (D:\\manufacture\\.tmp\\deek_brief_multi_account_ingestion.md)
will normalise these into a separate seller_account_id column. Until then,
keeping the variants in the country string is the least-lossy choice.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Real Amazon ASINs are exactly 10 alphanumeric chars (almost always
# starting with B for products created post-2008; older catalog items
# may use ISBN-shaped strings). Anything else in the ASIN column is
# spreadsheet noise — usually a stray note like "THIS IS SAME AS M0641"
# or "NOT LISTED YET". Treat non-matching values as None on ingest;
# the original text isn't lost (it stays in the source CSV) but
# nothing pretending to be an ASIN reaches the DB.
_ASIN_RE = re.compile(r'^[A-Z0-9]{10}$')

CLAW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAW_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(CLAW_ROOT / '.env')
except Exception:
    pass

from core.amazon_intel.db import get_conn


logger = logging.getLogger('ingest_stock_sheet')


# ── Normalisation ──────────────────────────────────────────────────────

# Country values to skip outright — these are spreadsheet-side notes
# that ended up in the COUNTRY column rather than channel labels.
_SKIP_COUNTRY_VALUES = frozenset({
    '',                        # 58 blank rows
    'OLD LISTING',
    'REUSE',
    'STOCK',
    'INACTIVE',                # treated as a separate marker; skip from canonical map
    'amazon',                  # too generic — no marketplace
    'ETSYOD001198',            # concatenated SKU/channel; manual fix needed
    'M0781 IS FREE TO USE',    # note text in country column
})

# Verbatim normalisation map. Keys compared after .strip() but before
# upper() to catch the lowercase 'amazon' / 'Etsy' variants explicitly.
_COUNTRY_NORMALISE = {
    'USA': 'US',
    'AUS': 'AU',
    'Etsy': 'ETSY',
    'etsy': 'ETSY',

    # FR / IT account-bearing variants — preserve the seller-account
    # signal in the country column. Underscore form so the value is
    # safely usable as a unique-index key without surprises around
    # whitespace.
    'FR CRAFTS':                       'FR_CRAFTS',
    'FR DESIGNED':                     'FR_DESIGNED',
    'FR DESIGNED - DUPLICATE CRAFTS':  'FR_DESIGNED_DUP_CRAFTS',
    'FR CRAFTS - DUPLICATE DESIGNED':  'FR_CRAFTS_DUP_DESIGNED',
    'IT DESIGNED':                     'IT_DESIGNED',
}


def _normalise_country(raw: str) -> str | None:
    """Map a raw COUNTRY cell to a canonical channel code.

    Returns None for rows that should be skipped.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped in _SKIP_COUNTRY_VALUES:
        return None
    if stripped in _COUNTRY_NORMALISE:
        return _COUNTRY_NORMALISE[stripped]
    # Final pass: collapse whitespace + uppercase. Catches "UK ", "IT ".
    cleaned = ' '.join(stripped.split()).upper()
    if cleaned in _SKIP_COUNTRY_VALUES:
        return None
    if cleaned in _COUNTRY_NORMALISE:
        return _COUNTRY_NORMALISE[cleaned]
    return cleaned


def _truthy(s: str) -> bool:
    """Loose 'is_personalised' parser — anything non-empty/non-no is true."""
    if not s:
        return False
    return s.strip().lower() in {'y', 'yes', 'true', '1', 'x'}


# ── Schema / snapshot ─────────────────────────────────────────────────

def _ensure_constraint(conn) -> None:
    """Drop UNIQUE (sku), add UNIQUE (sku, country). Idempotent."""
    with conn.cursor() as cur:
        # Drop the old single-column unique index if present
        cur.execute(
            "DROP INDEX IF EXISTS idx_ami_sku_sku"
        )
        # Add the new composite if not already present
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE tablename = 'ami_sku_mapping'
                      AND indexname = 'idx_ami_sku_sku_country'
                ) THEN
                    CREATE UNIQUE INDEX idx_ami_sku_sku_country
                        ON ami_sku_mapping (sku, country);
                END IF;
            END $$;
            """
        )
        conn.commit()


def _snapshot_table(conn) -> str:
    """Copy the current ami_sku_mapping into a timestamped backup table.

    Returns the backup table name so the caller can log it.
    """
    stamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    backup = f'ami_sku_mapping_backup_{stamp}'
    with conn.cursor() as cur:
        cur.execute(
            f'CREATE TABLE {backup} AS TABLE ami_sku_mapping'
        )
        conn.commit()
    return backup


# ── Ingest ────────────────────────────────────────────────────────────

def _parse_csv(path: Path) -> tuple[list[dict], dict]:
    """Yield normalised dicts ready for INSERT. Returns (rows, stats)."""
    rows: list[dict] = []
    stats = {
        'csv_total': 0,
        'skipped_blank_country': 0,
        'skipped_blank_sku': 0,
        'skipped_blank_m_number': 0,
        'skipped_noise_country': 0,
        'kept': 0,
        'by_country': {},
    }

    with open(path, encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)  # discard
        for raw in reader:
            stats['csv_total'] += 1
            # Pad short rows so positional access doesn't IndexError
            if len(raw) < 11:
                raw = raw + [''] * (11 - len(raw))

            sku        = (raw[0] or '').strip()
            m_number   = (raw[1] or '').strip()
            new_sku    = (raw[2] or '').strip() or None
            country_in = raw[3] or ''
            description = (raw[4] or '').strip() or None
            blank_name = (raw[5] or '').strip() or None
            is_pers    = _truthy(raw[6] or '')
            asin       = (raw[7] or '').strip() or None

            if not sku:
                stats['skipped_blank_sku'] += 1
                continue
            if not m_number:
                stats['skipped_blank_m_number'] += 1
                continue

            country = _normalise_country(country_in)
            if country is None:
                if (country_in or '').strip() == '':
                    stats['skipped_blank_country'] += 1
                else:
                    stats['skipped_noise_country'] += 1
                continue

            # 'Not Found' values from the spreadsheet's lookup helper
            # sometimes leak into NEW SKU / ASIN. Treat as null.
            if new_sku and new_sku.lower() == 'not found':
                new_sku = None
            if asin and asin.lower() == 'not found':
                asin = None

            # ASIN must be the canonical 10-char alphanumeric form.
            # Anything else is noise (a stray note in the wrong column,
            # a duplicate flag, etc.). Drop to None — caller's intent
            # is to record an Amazon ASIN here; if that's not what's
            # in the cell, recording the non-ASIN string is worse than
            # recording nothing.
            if asin and not _ASIN_RE.match(asin):
                asin = None

            rows.append({
                'sku': sku,
                'm_number': m_number,
                'new_sku': new_sku,
                'country': country,
                'description': description,
                'blank_name': blank_name,
                'is_personalised': is_pers,
                'asin': asin,
            })
            stats['kept'] += 1
            stats['by_country'][country] = stats['by_country'].get(country, 0) + 1

    return rows, stats


def _bulk_insert(conn, rows: list[dict]) -> int:
    """TRUNCATE + INSERT all rows. Returns count inserted."""
    with conn.cursor() as cur:
        cur.execute('TRUNCATE TABLE ami_sku_mapping RESTART IDENTITY')
        # In-memory dedupe on (sku, country) — last write wins, since
        # the unique index would refuse the second otherwise.
        seen: dict[tuple[str, str], dict] = {}
        for r in rows:
            seen[(r['sku'], r['country'])] = r
        deduped = list(seen.values())

        from psycopg2.extras import execute_values
        execute_values(
            cur,
            """
            INSERT INTO ami_sku_mapping
                (sku, m_number, new_sku, country, description, blank_name,
                 is_personalised, asin, source)
            VALUES %s
            """,
            [
                (
                    r['sku'], r['m_number'], r['new_sku'], r['country'],
                    r['description'], r['blank_name'],
                    r['is_personalised'], r['asin'], 'stock_sheet_2026_05_08',
                )
                for r in deduped
            ],
            template='(%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            page_size=500,
        )
        conn.commit()
        return len(deduped)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s ingest_stock_sheet — %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    csv_path = Path(os.environ.get(
        'STOCK_SHEET_CSV',
        '/app/data/uploads/stock_sheet_assembly.csv',
    ))
    if not csv_path.exists():
        logger.error('CSV not found at %s — set STOCK_SHEET_CSV env var', csv_path)
        return 2

    logger.info('CSV: %s', csv_path)

    rows, stats = _parse_csv(csv_path)
    logger.info('Parse stats:')
    for k, v in stats.items():
        if k != 'by_country':
            logger.info('  %-30s %s', k, v)

    if not rows:
        logger.error('zero rows kept after parse — refusing to truncate')
        return 1

    with get_conn() as conn:
        # Pre-check counts
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM ami_sku_mapping')
            before = cur.fetchone()[0]
        logger.info('Existing rows in ami_sku_mapping: %d', before)

        backup_table = _snapshot_table(conn)
        logger.info('Snapshot saved: %s', backup_table)

        _ensure_constraint(conn)
        logger.info('Constraint: idx_ami_sku_sku_country in place')

        inserted = _bulk_insert(conn, rows)
        logger.info('Inserted %d rows (deduped from %d kept)', inserted, len(rows))

        # Post-check
        with conn.cursor() as cur:
            cur.execute(
                "SELECT country, COUNT(*) FROM ami_sku_mapping "
                "GROUP BY country ORDER BY 2 DESC"
            )
            post = cur.fetchall()

    logger.info('Per-channel counts after ingest:')
    for country, n in post:
        logger.info('  %-30s %5d', country, n)

    return 0


if __name__ == '__main__':
    sys.exit(main())
