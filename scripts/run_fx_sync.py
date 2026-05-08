"""
Daily FX rate ingest into ami_fx_rates.

Pulls GBP/USD, GBP/EUR, GBP/CAD, GBP/AUD from frankfurter.app (free,
no auth, sourced from European Central Bank reference rates) and
UPSERTs one row per (as_of_date, currency_code) into ami_fx_rates.
GBP itself is also written with rate=1.0 so the lookup helper has a
literal row for the no-op case.

Designed to run in the deek-api container via cron:

    0 7 * * * docker exec -w /app -e PYTHONPATH=/app deploy-deek-api-1 \\
        python scripts/run_fx_sync.py >> /var/log/deek-fx-sync.log 2>&1

Idempotent — re-running on the same day overwrites the row, so a missed
fetch can be back-filled by hand without duplication. The script exits
0 even when the upstream API is unreachable; the lookup helper falls
back to the most recent within 7 days, then to a configured default.

Why frankfurter.app: rates published by the ECB at ~16:00 CET each
weekday. Free, rate-limited only at obvious-abuse levels, no API key
needed (which keeps the failure surface tiny — no token rotation, no
silent 401 like the SP-API cron episode burned us with on 2026-04-15).

Why 07:00 UTC: well after ECB rates publish (~15:00 UTC weekday),
before the 08:00 CRM email-review job, and within UK business hours
so a human noticing a failure can re-run manually.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# Resolve project root so this works whether called from /app inside
# the container or D:/deek/scripts on the dev box.
CLAW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAW_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(CLAW_ROOT / '.env')
except Exception:
    pass

import httpx

from core.amazon_intel.db import get_conn


logger = logging.getLogger('fx_sync')

# Free, no-auth ECB-sourced rates. Returns JSON like
# {"date":"2026-05-08","base":"GBP","rates":{"USD":1.2734,"EUR":1.1683,...}}
# Frankfurter migrated domains in 2026; old api.frankfurter.app 301s
# to api.frankfurter.dev/v1. httpx doesn't follow redirects by default
# so we hit the new URL directly.
FRANKFURTER_LATEST_URL = 'https://api.frankfurter.dev/v1/latest'

# Currencies we need GBP rates for. GBP itself goes in too with rate=1.0
# so the FX lookup helper has a row to read for the no-op case.
TARGET_CURRENCIES = ('USD', 'EUR', 'CAD', 'AUD')


def fetch_rates() -> tuple[dict[str, Decimal], date] | None:
    """Hit Frankfurter; return (rates_dict, as_of_date) or None on failure.

    Frankfurter returns rates as floats. We convert to Decimal at the
    boundary so all downstream math stays in Decimal — float arithmetic
    on financial values is the kind of bug that survives months in
    production before someone notices the pennies don't line up.
    """
    params = {'from': 'GBP', 'to': ','.join(TARGET_CURRENCIES)}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(FRANKFURTER_LATEST_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error('fetch_rates: upstream error: %s', exc)
        return None

    raw_rates = payload.get('rates') or {}
    raw_date = payload.get('date')
    if not raw_rates or not raw_date:
        logger.error('fetch_rates: malformed response: %r', payload)
        return None

    out: dict[str, Decimal] = {}
    for code in TARGET_CURRENCIES:
        v = raw_rates.get(code)
        if v is None:
            logger.warning('fetch_rates: missing %s in response', code)
            continue
        out[code] = Decimal(str(v))

    out['GBP'] = Decimal('1.0')

    try:
        as_of = date.fromisoformat(raw_date)
    except ValueError:
        logger.error('fetch_rates: bad date %r', raw_date)
        return None

    return out, as_of


def upsert_rates(rates: dict[str, Decimal], as_of: date, source: str) -> int:
    """Insert/update rows in ami_fx_rates. Returns count of rows touched."""
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for code, rate in rates.items():
                cur.execute(
                    """
                    INSERT INTO ami_fx_rates
                        (as_of_date, currency_code, unit_per_gbp, source)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (as_of_date, currency_code)
                    DO UPDATE SET
                        unit_per_gbp = EXCLUDED.unit_per_gbp,
                        source       = EXCLUDED.source,
                        fetched_at   = NOW()
                    """,
                    (as_of, code, rate, source),
                )
                n += 1
        conn.commit()
    return n


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s fx_sync — %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    result = fetch_rates()
    if result is None:
        logger.warning(
            'no rates fetched — lookup helper will fall back to the '
            'most recent DB row (≤7 days) or the configured default. '
            'Cron will retry tomorrow.'
        )
        return 0  # not an error — fallback path is healthy

    rates, as_of = result
    n = upsert_rates(rates, as_of, source='frankfurter.app')
    logger.info(
        'fx sync ok: as_of=%s rows=%d %s',
        as_of, n,
        ' '.join(f'{c}={v}' for c, v in sorted(rates.items())),
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
