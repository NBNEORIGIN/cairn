"""
Manufacture cost tools — bridge from Deek to the Manufacture module's
cost endpoint so the agent can answer profit / margin / COGS questions
without spending 12 tool rounds fishing in the wiki.

Backstory: a chat on 2026-04-30 ("estimate monthly profit from
personalised orders") burned the full MAX_TOOL_ROUNDS=12 budget because
Deek had no tool that could reach Manufacture's cost data. The model
correctly diagnosed the gap on round 1 ("Manufacture has cost info
via an API endpoint, but I don't have a tool that hits it") and then
spent the next eleven rounds wiki-searching for cost numbers that
weren't there. This tool closes that gap.

The endpoint exists already — Manufacture exposes
``GET /api/costs/price/bulk/`` and there is a sync-side helper
``core.amazon_intel.manufacture_client.get_costs_bulk()`` that uses
it. That helper is async (used inside FastAPI handlers) — we cannot
call it from a sync tool function without spinning a fresh event
loop, so this module replicates the HTTP call directly with
``httpx.Client`` to match the rest of the sync tool surface.

Auth: Bearer ``DEEK_API_KEY`` (with CAIRN/CLAW back-compat aliases) —
same shared-secret pattern as the CRM tools. Manufacture's middleware
checks the same env var on the other side.

Config:
    DEEK_API_KEY           — shared bearer (required; empty disables)
    MANUFACTURE_API_URL    — default https://manufacture.nbnesigns.co.uk
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from .registry import Tool, RiskLevel


MANUFACTURE_DEFAULT_BASE_URL = 'https://manufacture.nbnesigns.co.uk'
MANUFACTURE_COSTS_PATH = '/api/costs/price/bulk/'
MANUFACTURE_REQUEST_TIMEOUT = 30.0  # seconds — bulk costs can be slow

# Cap on how many M-numbers we'll pass in a single call. Mirrors the
# 2000 cap in core.amazon_intel.manufacture_client.get_costs_bulk —
# longer URLs risk hitting nginx/Cloudflare 414 limits.
MAX_M_NUMBERS_PER_CALL = 500
# How many cost records to format inline before saying "...and N more".
# The model can re-ask with a narrower m_numbers filter if it wants more.
MAX_RECORDS_INLINE = 50


def _bearer_token() -> str:
    return (
        os.getenv('DEEK_API_KEY')
        or os.getenv('CAIRN_API_KEY')
        or os.getenv('CLAW_API_KEY', '')
        or os.getenv('MANUFACTURE_API_KEY', '')
    ).strip()


def _manufacture_base() -> str:
    return (os.getenv('MANUFACTURE_API_URL') or MANUFACTURE_DEFAULT_BASE_URL).rstrip('/')


def _normalise_m_numbers(raw: list[str] | str | None) -> list[str]:
    """Accept either a list of M-numbers or a CSV string. Strip + dedupe + sort.

    The agent loop sometimes hands `m_numbers` in as a list and sometimes
    as a comma-separated string depending on which model emitted the
    tool_call — be liberal in what we accept.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(',')]
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw]
    else:
        return []
    return sorted({m for m in items if m})


def _format_overhead(overhead: dict) -> str:
    """One-line summary of the overhead_context block. Tolerates missing
    fields — the schema may grow over time."""
    if not overhead:
        return ''
    bits: list[str] = []
    monthly = overhead.get('monthly_overhead_gbp')
    if monthly is not None:
        bits.append(f'monthly_overhead=£{monthly:,.0f}')
    for key in ('b2b_revenue_gbp', 'ebay_revenue_gbp', 'amazon_revenue_gbp'):
        v = overhead.get(key)
        if v is not None:
            bits.append(f'{key}=£{v:,.0f}')
    return ' · '.join(bits) if bits else ''


def _format_cost_record(m_number: str, rec: dict) -> str:
    """Render one cost row into a single line. Pulls the fields most
    likely to be useful for profit math; falls back gracefully if the
    schema changes."""
    bits: list[str] = [f'  {m_number}:']
    # Try common cost-component field names — Manufacture's schema may
    # use any of these. Whichever are present, surface them.
    for label, keys in [
        ('cost', ('total_cost_gbp', 'cost_gbp', 'cost', 'unit_cost')),
        ('material', ('material_cost_gbp', 'material_cost', 'materials')),
        ('labour', ('labour_cost_gbp', 'labour_cost', 'labour')),
        ('packaging', ('packaging_cost_gbp', 'packaging_cost', 'packaging')),
        ('price', ('list_price_gbp', 'price_gbp', 'price', 'rrp')),
        ('margin', ('margin_gbp', 'margin', 'gross_margin_gbp')),
    ]:
        for k in keys:
            if k in rec and rec[k] is not None:
                try:
                    bits.append(f'{label}=£{float(rec[k]):.2f}')
                except (TypeError, ValueError):
                    bits.append(f'{label}={rec[k]}')
                break
    name = rec.get('name') or rec.get('description') or rec.get('product_name')
    if name:
        bits.append(f'({str(name)[:60]})')
    return ' '.join(bits)


def _get_sku_costs(
    project_root: str,
    m_numbers: list[str] | str | None = None,
    **kwargs,
) -> str:
    """Tool entry point — fetches Manufacture cost breakdown by M-number.

    No m_numbers → server returns the full catalogue (capped at whatever
    Manufacture's pagination is). For "estimate profit on personalised
    orders" type questions, the model should usually pass the M-numbers
    of the products it's interested in (which it'll get from a CRM or
    Amazon-intel query first).
    """
    token = _bearer_token()
    if not token:
        return (
            'get_sku_costs unavailable: DEEK_API_KEY is not set. '
            'This tool calls Manufacture server-to-server with a shared '
            'token — set DEEK_API_KEY in the deek-api env to enable.'
        )

    m_list = _normalise_m_numbers(m_numbers)
    capped = False
    if len(m_list) > MAX_M_NUMBERS_PER_CALL:
        m_list = m_list[:MAX_M_NUMBERS_PER_CALL]
        capped = True

    params: dict[str, Any] = {}
    if m_list:
        params['m_numbers'] = ','.join(m_list)

    base = _manufacture_base()
    url = f'{base}{MANUFACTURE_COSTS_PATH}'

    try:
        with httpx.Client(timeout=MANUFACTURE_REQUEST_TIMEOUT) as client:
            r = client.get(
                url,
                params=params,
                headers={'Authorization': f'Bearer {token}'},
            )
    except httpx.TimeoutException:
        return (
            f'get_sku_costs timed out after {MANUFACTURE_REQUEST_TIMEOUT:.0f}s — '
            f'Manufacture API at {base} may be slow or unreachable.'
        )
    except Exception as exc:
        return f'get_sku_costs error: {type(exc).__name__}: {exc}'

    if r.status_code == 401:
        return (
            'get_sku_costs unauthorized: the Bearer token in DEEK_API_KEY '
            'was rejected by Manufacture. Check that the token on this '
            'side matches DEEK_API_KEY in the Manufacture container.'
        )
    if r.status_code == 404:
        return (
            f'get_sku_costs: Manufacture endpoint not found at {url}. '
            f'The /api/costs/price/bulk/ endpoint may not be deployed on '
            f'this environment.'
        )
    if r.status_code == 429:
        return 'get_sku_costs rate-limited (429) — retry in a moment.'
    if r.status_code >= 500:
        return f'get_sku_costs: server error {r.status_code} from {base}.'
    if r.status_code != 200:
        return f'get_sku_costs: unexpected HTTP {r.status_code} from {base}: {r.text[:300]}'

    try:
        data = r.json() or {}
    except Exception as exc:
        return f'get_sku_costs: could not parse response body ({exc})'

    results = data.get('results') or []
    overhead = data.get('overhead_context') or {}

    if not results:
        if m_list:
            return (
                f'No Manufacture cost records found for the {len(m_list)} '
                f'M-number(s) requested. Either the M-numbers don\'t exist '
                f'in Manufacture\'s product table or they have no cost data.'
            )
        return 'get_sku_costs: Manufacture returned no cost records.'

    lines: list[str] = []
    n_total = len(results)
    note = ''
    if capped:
        note = (f' (request capped at {MAX_M_NUMBERS_PER_CALL} M-numbers; '
                f'split into multiple calls if you need more)')
    if m_list:
        lines.append(f'Manufacture cost records — {n_total} of {len(m_list)} M-numbers requested{note}:')
    else:
        lines.append(f'Manufacture cost records — {n_total} returned (no filter){note}:')

    overhead_summary = _format_overhead(overhead)
    if overhead_summary:
        lines.append(f'Overhead context: {overhead_summary}')

    lines.append('')
    for rec in results[:MAX_RECORDS_INLINE]:
        m_number = rec.get('m_number') or '?'
        lines.append(_format_cost_record(m_number, rec))

    if n_total > MAX_RECORDS_INLINE:
        lines.append('')
        lines.append(
            f'…and {n_total - MAX_RECORDS_INLINE} more. Pass a narrower '
            f'm_numbers filter to drill in.'
        )

    return '\n'.join(lines)


get_sku_costs_tool = Tool(
    name='get_sku_costs',
    description=(
        'Fetch product cost data (COGS, material, labour, packaging) and '
        'overhead context from the NBNE Manufacture module. Use this for '
        'ANY question about profit, margin, COGS, cost per SKU, or '
        '"how much does it cost us to make X". Wraps Manufacture\'s '
        'GET /api/costs/price/bulk/ endpoint.\n\n'
        'Arguments: m_numbers (optional list or CSV string of NBNE '
        'M-numbers like "M3089,M3090,M3091" — pass the M-numbers you\'re '
        'interested in to keep the response small. With no filter, '
        'returns the full catalogue capped by server-side pagination).\n\n'
        'Returns a formatted summary with cost components per SKU plus '
        'a one-line overhead_context summary (monthly overhead, B2B '
        'revenue split). For profit calculations, combine this with '
        'revenue from query_amazon_intel() (Amazon orders) or '
        'search_crm() (B2B/CRM jobs) — Deek does not have direct '
        'access to cost data anywhere else, so do NOT try to compute '
        'profit by reading wiki articles or grepping source.'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_get_sku_costs,
    required_permission='get_sku_costs',
)


__all__ = ['get_sku_costs_tool']
