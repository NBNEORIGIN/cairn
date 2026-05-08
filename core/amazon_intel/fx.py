"""
FX rate lookup + GBP conversion.

Owns three concerns:

1. **Marketplace → currency mapping.** UK is GBP, US is USD, DE/FR/IT/ES/NL
   are EUR, CA is CAD, AU is AUD. Currencies the business doesn't trade in
   right now (SEK, PLN, TRY, MXN, INR, JPY, etc.) are listed but route to
   `None` and the caller should treat the marketplace as 1.0-pass-through
   so the math doesn't crash on a future spurious row.

2. **Rate lookup with graceful fallback.**
     a. Today's rate from `ami_fx_rates`
     b. Most recent rate from the last 7 days
     c. Hardcoded business-default rate (set 2026-05-08, refreshed manually
        if it drifts more than ~10%)
     d. 1.0 — last-resort no-op so the math still produces a number rather
        than a 500. Logged so the pre-mortem is visible in audit.

3. **`convert_to_gbp(amount, currency)`** — the one public conversion
   function the margin engine calls. Returns the input unchanged when
   `currency == 'GBP'` so the UK code path is a literal no-op (verifiable
   by inspection — UK numbers stay byte-identical after this change ships).

Diagnosed 2026-05-08 from a US worked example: 6 units of M0001 at $14.57
net produced "$32.18 net profit" because Cairn was subtracting £12.72 COGS
directly from $87.44 revenue. Truth in GBP was £22.63. Per-marketplace
COGS overrides made the FX gap a hard blocker — couldn't ship the brief
correctly until this landed.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from .db import get_conn


logger = logging.getLogger(__name__)


# ── Marketplace → currency ────────────────────────────────────────────────

# Amazon marketplace code → ISO 4217 currency. Aliases (UK and GB) collapse
# to the same currency. None means "we don't currently trade here" — the
# caller should treat any row with a None currency as 1.0-pass-through to
# avoid crashing on a stray row from a marketplace that's been disabled
# or never enabled.
_MARKETPLACE_CURRENCY: dict[str, Optional[str]] = {
    'UK': 'GBP', 'GB': 'GBP',
    'US': 'USD',
    'CA': 'CAD',
    'AU': 'AUD',
    'DE': 'EUR', 'FR': 'EUR', 'IT': 'EUR', 'ES': 'EUR', 'NL': 'EUR',
    # Listed-but-unsupported marketplaces — return None so the caller's
    # fallback path kicks in rather than us silently converting at 1:1.
    'SE': None,  # SEK
    'PL': None,  # PLN
    'TR': None,  # TRY
    'MX': None,  # MXN
    'IN': None,  # INR
    'JP': None,  # JPY
    'BR': None,  # BRL
    'AE': None,  # AED
    'SA': None,  # SAR
    'EG': None,  # EGP
}

# Hard-coded business-default rates — used only when the DB has no row in
# the last 7 days AND the daily ingest is failing. Set 2026-05-08 from
# rough current-quarter averages; if the daily fetch is healthy these are
# never read. Refresh manually if any rate drifts more than ~10%.
_DEFAULT_RATES: dict[str, Decimal] = {
    'GBP': Decimal('1.0'),
    'USD': Decimal('1.27'),
    'EUR': Decimal('1.17'),
    'CAD': Decimal('1.72'),
    'AUD': Decimal('1.92'),
}


def marketplace_currency(marketplace: str) -> Optional[str]:
    """Return the ISO 4217 currency for a marketplace, or None if untraded."""
    return _MARKETPLACE_CURRENCY.get((marketplace or '').upper())


# ── Rate lookup ───────────────────────────────────────────────────────────

# Module-level cache, keyed by (currency_code, target_date). Lookups are
# cheap (one row), but compute_margins reads the same rate for every
# row in a per-marketplace request — caching once per request is the
# obvious win. Cleared per-process; not shared across containers.
_rate_cache: dict[tuple[str, date], Decimal] = {}


def _read_rate_from_db(
    currency_code: str,
    as_of: Optional[date] = None,
) -> Optional[tuple[Decimal, date]]:
    """Read a rate from `ami_fx_rates`.

    When ``as_of`` is None: latest row within the last 7 days
    (live-rate behaviour for current-day margin calculations).

    When ``as_of`` is set: nearest row within ±7 days of that date,
    preferring on-or-before. Used by historical-period operations
    like the Etsy ad-spend ingest, which uploads April spend in May
    and wants April's average rate. Picking on-or-before first means
    a backfill in May for April uses the late-April rate, not the
    early-May rate — closer to the truth for monthly averages.

    Returns (unit_per_gbp, as_of_date) or None if nothing usable found.
    """
    if as_of is None:
        sql = """
            SELECT unit_per_gbp, as_of_date
              FROM ami_fx_rates
             WHERE currency_code = %s
               AND as_of_date >= CURRENT_DATE - INTERVAL '7 days'
             ORDER BY as_of_date DESC
             LIMIT 1
        """
        params: tuple = (currency_code.upper(),)
    else:
        # Two-step: nearest on-or-before within 7 days, else nearest
        # after within 7 days. Done in one query via ORDER BY a
        # custom signed-distance expression so the LIMIT 1 picks the
        # closest match, with on-or-before tiebreaking when distance
        # is equal.
        sql = """
            SELECT unit_per_gbp, as_of_date
              FROM ami_fx_rates
             WHERE currency_code = %s
               AND as_of_date BETWEEN %s::date - INTERVAL '7 days'
                                   AND %s::date + INTERVAL '7 days'
             ORDER BY ABS(as_of_date - %s::date) ASC,
                      (as_of_date <= %s::date) DESC
             LIMIT 1
        """
        params = (currency_code.upper(), as_of, as_of, as_of, as_of)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if not row:
                    return None
                rate, as_of_date = row
                return Decimal(str(rate)), as_of_date
    except Exception as exc:
        logger.warning('fx db lookup failed for %s: %s', currency_code, exc)
        return None


def get_rate(
    currency_code: str,
    as_of: Optional[date] = None,
) -> Decimal:
    """Return ``unit_per_gbp`` for the currency.

    1 GBP = N <currency>. Multiply GBP by this to get the foreign amount.
    Divide a foreign amount by this to get GBP.

    GBP returns Decimal('1.0') without touching the DB.

    ``as_of`` (optional): historical date for backfill / late-uploaded
    data (e.g. monthly Etsy ad spend uploaded in the following month).
    When set, the lookup walks ami_fx_rates for the row nearest that
    date. When None (the common case), today's live rate is used.

    Resolution order:
        1. ami_fx_rates row matching ``as_of`` (or today, if None)
        2. Hardcoded _DEFAULT_RATES fallback
        3. Decimal('1.0') with a warning if the currency is unknown
    """
    code = (currency_code or '').upper()
    if code == 'GBP':
        return Decimal('1.0')

    cache_key = (code, as_of or date.today())
    cached = _rate_cache.get(cache_key)
    if cached is not None:
        return cached

    db_lookup = _read_rate_from_db(code, as_of=as_of)
    if db_lookup is not None:
        rate, _as_of = db_lookup
        _rate_cache[cache_key] = rate
        return rate

    default = _DEFAULT_RATES.get(code)
    if default is not None:
        logger.warning(
            'fx: no DB rate for %s near %s — using configured default %s',
            code, (as_of or 'today'), default,
        )
        _rate_cache[cache_key] = default
        return default

    logger.error(
        'fx: no DB rate AND no default for %s — using 1.0 (math will be wrong)',
        code,
    )
    rate = Decimal('1.0')
    _rate_cache[cache_key] = rate
    return rate


def bulk_rates(*, codes: Optional[list[str]] = None) -> dict[str, float]:
    """Return today's rates for a list of currency codes (or all known
    business currencies if no list given).

    Used by /ami/margin/per-sku to surface ``fx_rate_used`` in the response
    so spot-checks against a known reference rate are possible. Output is
    plain ``float`` for JSON-friendliness — Decimal would need a custom
    encoder. Acceptable here because these are display rates with at most
    4 decimals of precision; the conversion math itself stays in Decimal.
    """
    if codes is None:
        codes = ['USD', 'EUR', 'CAD', 'AUD', 'GBP']
    out: dict[str, float] = {}
    for c in codes:
        out[c.upper()] = float(get_rate(c))
    return out


def convert_to_gbp(
    amount: Decimal,
    currency: Optional[str],
    as_of: Optional[date] = None,
) -> Decimal:
    """Convert a Decimal amount in ``currency`` to GBP.

    GBP / None / unknown currency code passes through unchanged so the
    UK code path is a true no-op. The caller decides whether to treat
    a None currency as "this row should be skipped" vs "1:1 was OK".

    ``as_of``: historical date for backfill conversions (e.g. April
    Etsy ad spend uploaded in May). When None, uses today's rate.
    """
    if amount is None:
        return amount
    if currency is None:
        return amount
    code = currency.upper()
    if code == 'GBP':
        return amount
    rate = get_rate(code, as_of=as_of)
    if rate <= 0:
        return amount  # last-ditch — should never happen, log already emitted
    return (amount / rate)


def clear_cache() -> None:
    """Test hook — drop the request-scoped cache. Call in tests that
    insert fresh rows into ami_fx_rates and want the next get_rate to
    re-read."""
    _rate_cache.clear()
