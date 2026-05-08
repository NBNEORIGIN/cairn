"""
Database schema and query helpers for eBay Intelligence.

Tables use the ``ebay_`` prefix to namespace within Deek's Postgres.
Mirrors the Etsy module structure (`core/etsy_intel/db.py`):

  ebay_oauth_tokens   — OAuth 2.0 token storage (one row per environment)
  ebay_listings       — Minimal analytics-side mirror; Render owns the
                        catalogue. Stores item_id + sku + title +
                        m_number for margin-engine joins ONLY.
  ebay_sales          — Order line items; PII-scrubbed per Manufacture's
                        existing convention (no buyer name/email/address).
  ebay_ad_spend       — Promoted Listings spend per (item_id, period).

Architecture decisions per the 2026-05-08 brief:

  * eBay OAuth lives in Deek (Option A from the brief). Manufacture's
    sales_velocity adapter switches to consume `/ebay/sales` from Deek
    rather than calling eBay directly — same pattern as Etsy.

  * Listings table is minimal — item_id / sku / title / m_number /
    state. Render is system-of-record for the full catalogue (price,
    quantity_available, descriptions, images, policies). Deek's
    ebay_listings exists only for margin-engine joins.

  * Sales schema explicitly excludes buyer name / email / address.
    eBay returns these on the order response; we whitelist only what
    margin/profitability needs (sku, quantity, line ids, sale_date,
    buyer_country for VAT). PII boundary documented and DO NOT add
    buyer-PII columns without re-reviewing the data minimisation rule.
"""
import os
import psycopg2
from contextlib import contextmanager


def get_db_url() -> str:
    return os.getenv('DATABASE_URL', 'postgresql://postgres:postgres123@localhost:5432/deek')


@contextmanager
def get_conn():
    conn = psycopg2.connect(get_db_url(), connect_timeout=5)
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema():
    """Create all ebay_* tables if they don't exist."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_SCHEMA)
            conn.commit()


_SQL_SCHEMA = """
-- OAuth 2.0 tokens for eBay's REST APIs (sell.* family).
-- One row per (environment, app_user) — production is the only env
-- NBNE uses today; sandbox is supported for dev.
--
-- Token lifecycle:
--   access_token   ~2-hour expiry
--   refresh_token  18-month rotation (eBay's standard)
--
-- Refresh logic uses SELECT FOR UPDATE to avoid races between the
-- web process and any cron-driven sync — matches the pattern
-- Manufacture's sales_velocity/adapters/ebay.py uses today.
CREATE TABLE IF NOT EXISTS ebay_oauth_tokens (
    id              SERIAL PRIMARY KEY,
    environment     TEXT NOT NULL DEFAULT 'production',
    user_id         TEXT,                              -- eBay user reference (optional, scope-dependent)
    access_token    TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    scopes          TEXT,
    state           TEXT,                              -- transient OAuth state during consent flow
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT ebay_oauth_tokens_env_unique UNIQUE (environment)
);

-- Minimal analytics-side mirror. Render is system-of-record for the
-- full catalogue; this table only stores fields the margin engine
-- needs to join + display. NEVER add price / quantity_available /
-- description / image_urls — those belong to Render.
CREATE TABLE IF NOT EXISTS ebay_listings (
    id                 SERIAL PRIMARY KEY,
    item_id            BIGINT UNIQUE NOT NULL,
    sku                TEXT,                            -- merchant SKU; joins to ami_sku_mapping.sku
    title              TEXT,                            -- shown in margin response for human ID
    state              TEXT,                            -- 'active' / 'ended' / 'inactive'
    m_number           TEXT,                            -- backfilled from ami_sku_mapping (country='EBAY')
    last_synced        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ebay_listings_sku
    ON ebay_listings(sku);
CREATE INDEX IF NOT EXISTS idx_ebay_listings_m_number
    ON ebay_listings(m_number);
CREATE INDEX IF NOT EXISTS idx_ebay_listings_state
    ON ebay_listings(state);

-- Order line items. PII boundary:
--   * INCLUDED: order_id, line_item_id, sku, quantity, prices,
--               sale_date, buyer_country (for VAT)
--   * EXCLUDED: buyer_name, buyer_email, buyer_address (Manufacture's
--               existing whitelist; do not relax without revisiting)
--
-- Currency assumption: NBNE eBay listings are GBP-priced on eBay UK;
-- non-UK buyers pay GBP-equivalent at checkout. v1 treats all values
-- as GBP. If NBNE ever lists on eBay.de or eBay.com, plug in the FX
-- helper from core/amazon_intel/fx.py (already date-keyed).
CREATE TABLE IF NOT EXISTS ebay_sales (
    id                 SERIAL PRIMARY KEY,
    order_id           TEXT NOT NULL,                   -- new persistent format
    legacy_order_id    TEXT,                            -- legacy format; kept for cross-reference with seller hub UI
    line_item_id       TEXT NOT NULL,
    item_id            BIGINT,                          -- soft FK to ebay_listings.item_id
    sku                TEXT,
    quantity           INTEGER NOT NULL DEFAULT 0,
    unit_price         NUMERIC(10,2),                   -- per-unit listing price
    total_price        NUMERIC(10,2),                   -- line total (unit_price * quantity)
    shipping_cost      NUMERIC(10,2),                   -- per-line allocation if available; 0 if order-level only
    total_paid         NUMERIC(10,2),                   -- includes shipping for this line
    fees               NUMERIC(10,2),                   -- API-derived FVF + payment processing when present, NULL when missing (margin engine falls back to rate card)
    currency           TEXT DEFAULT 'GBP',
    buyer_country      TEXT,                            -- ISO code; for VAT logic. NULL → treat as net (no divisor)
    fulfillment_status TEXT,
    payment_status     TEXT,
    sale_date          TIMESTAMPTZ,
    last_synced        TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT ebay_sales_unique_line UNIQUE (order_id, line_item_id)
);
CREATE INDEX IF NOT EXISTS idx_ebay_sales_date
    ON ebay_sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_ebay_sales_item
    ON ebay_sales(item_id);
CREATE INDEX IF NOT EXISTS idx_ebay_sales_sku
    ON ebay_sales(sku);

-- Promoted Listings spend (eBay marketing API).
-- Same source-versioned shape as etsy_ad_spend so future paths
-- (manual_paste_v1 fallback) can coexist on the same table.
-- Column names align with etsy_ad_spend where the concept is the
-- same (clicks, spend, spend_gbp, source) for cross-channel rollup
-- ergonomics. eBay-specific concepts (impressions vs views, sold
-- quantity vs orders attributed) keep their eBay names.
CREATE TABLE IF NOT EXISTS ebay_ad_spend (
    id              SERIAL PRIMARY KEY,
    item_id         BIGINT NOT NULL REFERENCES ebay_listings(item_id),
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    impressions     INTEGER,
    clicks          INTEGER,
    sold_quantity   INTEGER,
    sales           NUMERIC(10,2),                       -- attributed sales (eBay's term)
    spend           NUMERIC(10,2) NOT NULL,              -- in source currency
    spend_gbp       NUMERIC(10,2) NOT NULL,
    source_currency TEXT NOT NULL DEFAULT 'GBP',
    fx_rate_used    NUMERIC(10,6),
    source          TEXT NOT NULL DEFAULT 'ebay_api_v1',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT ebay_ad_spend_period_chk CHECK (period_end >= period_start),
    CONSTRAINT ebay_ad_spend_unique UNIQUE (item_id, period_start, period_end)
);
CREATE INDEX IF NOT EXISTS idx_ebay_ad_spend_item
    ON ebay_ad_spend(item_id);
CREATE INDEX IF NOT EXISTS idx_ebay_ad_spend_period
    ON ebay_ad_spend(period_start, period_end);
"""
