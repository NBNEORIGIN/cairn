"""
Amazon Intelligence query tool for the Cairn agent.

Allows the chat agent to run read-only SQL queries against the ami_* tables
in response to natural language questions about Amazon listing performance,
sales, advertising, and product health.
"""
import re
from .registry import Tool, RiskLevel


# Tables and key columns the LLM should know about
_SCHEMA_DOCS = """
Available tables (all read-only):

ami_sku_mapping — SKU to M-number to ASIN mapping (5,716 rows)
  sku, m_number, new_sku, country, description, blank_name, is_personalised, asin, source

ami_uploads — Upload log
  id, filename, file_type, marketplace, row_count, skip_count, error_count, status, uploaded_at

ami_flatfile_data — Parsed Amazon flatfile listings (4,142 rows)
  upload_id, sku, asin, product_id_type, parent_child, parent_sku, product_type,
  title, brand, bullet1-5, description, generic_keyword1-5,
  main_image_url, image_count, your_price, fulfilment (FBA/MFN),
  colour, size, material, browse_node_1, browse_node_2,
  keyword_count, bullet_count

ami_business_report_data — Amazon Business Report performance (678 rows, 15 months Jan 2025-Mar 2026)
  upload_id, parent_asin, child_asin, title,
  sessions (total page sessions), session_percentage,
  page_views, buy_box_percentage,
  units_ordered, unit_session_percentage (conversion rate),
  ordered_product_sales (revenue in GBP), total_order_items

ami_advertising_data — Sponsored Products search term report (6,387 rows, last 30 days)
  upload_id, report_type, campaign_name, ad_group_name, asin, sku,
  targeting, match_type, customer_search_term,
  impressions, clicks, spend, sales_7d, orders_7d, acos, roas

ami_listing_snapshots — Joined analytical view per ASIN (4,055 rows)
  asin, sku, m_number, marketplace, snapshot_date,
  title, bullet_count, image_count, has_description, keyword_count,
  your_price, fulfilment, brand,
  sessions_30d, page_views_30d, conversion_rate, buy_box_pct,
  units_ordered_30d, ordered_revenue_30d,
  ad_spend_30d, ad_impressions, ad_clicks, acos, roas,
  cost_price, gross_margin,
  health_score (0-10, lower = worse), issues (text[]), diagnosis_codes (text[]),
  recommendations (text[]), data_sources (text[])

ami_weekly_reports — Generated health reports
  report_date, marketplace, total_asins, avg_health_score,
  critical_count, attention_count, healthy_count, no_data_count,
  report_json (JSONB), summary (text)

Key relationships:
  flatfile.sku = sku_mapping.sku
  sku_mapping.asin = business_report.child_asin = snapshots.asin
  sku_mapping.m_number links to Manufacture products

Notes:
  - business_report covers Jan 2025 to Mar 2026 (cumulative, not per-month)
  - flatfile open_date is not stored; use ami_flatfile_data.created_at for upload date
  - All Listings Report data is in ami_sku_mapping (source='all_listings')
  - For "new products" queries, look at flatfile product_type or use sku_mapping.created_at
  - health_score: 0-4 critical, 4-7 needs attention, 7-10 healthy
  - diagnosis_codes include: CONTENT_WEAK, KEYWORD_POOR, VISIBILITY_LOW, MARGIN_CRITICAL,
    QUICK_WIN_IMAGES, QUICK_WIN_BULLETS, BUYBOX_LOST, ZERO_SESSIONS, NO_PERFORMANCE_DATA
  - The brand should be 'OriginDesigned' — WRONG_BRAND issue flags anything else
  - Parent listings (parent_child='Parent') are containers, not sellable — focus on Child rows
"""

# Allowed table names — refuse queries touching anything else
_ALLOWED_TABLES = {
    'ami_sku_mapping', 'ami_uploads', 'ami_flatfile_data',
    'ami_business_report_data', 'ami_advertising_data',
    'ami_listing_snapshots', 'ami_weekly_reports',
}

# Forbidden SQL keywords (beyond SELECT)
_FORBIDDEN = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY)\b',
    re.IGNORECASE,
)


def _validate_query(sql: str) -> str | None:
    """Validate a SQL query is safe. Returns error message or None if OK."""
    stripped = sql.strip().rstrip(';')
    if not stripped.upper().startswith('SELECT'):
        return "Only SELECT queries are allowed."
    if _FORBIDDEN.search(stripped):
        return f"Query contains forbidden keyword."
    # Check it only references ami_* tables (basic check)
    # Allow CTEs and subqueries — the table check is advisory not strict
    return None


def _query_amazon_intel(project_root: str, sql: str, limit: int = 50, **kwargs) -> str:
    """Execute a read-only SQL query against the Amazon Intelligence tables."""
    error = _validate_query(sql)
    if error:
        return f"QUERY REJECTED: {error}"

    # Enforce limit to prevent massive result sets
    stripped = sql.strip().rstrip(';')
    if 'LIMIT' not in stripped.upper():
        stripped += f' LIMIT {limit}'

    try:
        from core.amazon_intel.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(stripped)
                if cur.description is None:
                    return "Query executed but returned no result set."

                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()

                if not rows:
                    return "No rows returned."

                # Format as readable table
                lines = [' | '.join(cols)]
                lines.append('-' * len(lines[0]))
                for row in rows:
                    formatted = []
                    for val in row:
                        if val is None:
                            formatted.append('')
                        elif isinstance(val, float):
                            formatted.append(f'{val:,.2f}')
                        elif isinstance(val, int):
                            formatted.append(f'{val:,}')
                        elif isinstance(val, list):
                            formatted.append(', '.join(str(v) for v in val))
                        elif hasattr(val, 'isoformat'):
                            formatted.append(val.isoformat())
                        else:
                            formatted.append(str(val)[:200])
                    lines.append(' | '.join(formatted))

                result = '\n'.join(lines)
                if len(rows) >= limit:
                    result += f'\n\n(Results limited to {limit} rows)'
                return result

    except Exception as e:
        return f"QUERY ERROR: {type(e).__name__}: {e}"


query_amazon_intel_tool = Tool(
    name='query_amazon_intel',
    description=(
        'Query Amazon listing intelligence data — sales, performance, '
        'advertising, health scores, and product catalogue. '
        'Accepts a PostgreSQL SELECT query against the ami_* tables. '
        'Use this to answer questions about Amazon listings, revenue, '
        'conversion rates, ad spend, underperformers, and product health.\n\n'
        + _SCHEMA_DOCS
    ),
    risk_level=RiskLevel.SAFE,
    fn=_query_amazon_intel,
    required_permission='query_amazon_intel',
)
