"""Quote intelligence endpoints (Deek-side, read-mostly).

Three endpoints consumed by the CRM's quote editor sidebar and
by chat agent tools:

  GET  /api/deek/quotes/context?project_id=<id>[&query=<text>]
  GET  /api/deek/quotes/similar?query=<text>&limit=<n>
  POST /api/deek/quotes/review  (shadow-mode gated)

All auth via the usual Bearer middleware.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

from api.middleware.auth import verify_api_key

log = logging.getLogger(__name__)
router = APIRouter(prefix='/quotes', tags=['Quote Intelligence'])


def _connect():
    import psycopg2
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None
    try:
        return psycopg2.connect(db_url, connect_timeout=5)
    except Exception as exc:
        log.warning('[quotes] db connect failed: %s', exc)
        return None


@router.get('/context')
async def quote_context(
    project_id: str = Query(..., min_length=1),
    query: str | None = Query(default=None),
    _: bool = Depends(verify_api_key),
) -> JSONResponse:
    """Composite context for the quote editor sidebar.

    Shape:
      {
        project_id, project_name, query_used,
        client: { name, payment_record, prior_quotes: [...] },
        similar_jobs: [...],
        margin_reference: { sample_size, quoted_range_low/median/high, ... },
        lessons_learned: [...],
        generated_at, cache_ttl_seconds, warnings
      }

    Never errors at the top level — missing sections return empty
    so the sidebar can render what's available.
    """
    from core.intel.quote_context import get_quote_context
    ctx = get_quote_context(project_id, query=query)
    return JSONResponse(ctx)


@router.get('/similar')
async def quote_similar(
    query: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    _: bool = Depends(verify_api_key),
) -> JSONResponse:
    """Thin search_crm wrapper scoped to project rows with quoted
    values — the 'show me 5 quotes that look like this' button.
    """
    from core.intel.quote_context import search_similar_quotes
    results = search_similar_quotes(query, limit=limit)
    return JSONResponse({'results': results, 'total': len(results)})


@router.post('/review')
async def quote_review(
    payload: dict = Body(...),
    _: bool = Depends(verify_api_key),
) -> JSONResponse:
    """Sanity-check a drafted quote against historical patterns.

    Request body:
      {
        "project_id": "...",
        "total_inc_vat": 2850.0,
        "scope_summary": "...",
        "line_items_summary": "..."
      }

    Response:
      {
        "verdict": "ok" | "investigate" | "flag",
        "reasoning": "<short, user-facing>",
        "signals": [...],
        "shadow_mode": bool,
        "shadow_verdict": <real verdict when shadow_mode=true>
      }

    Shadow-mode-gated via DEEK_QUOTE_REVIEW_SHADOW (default true).
    In shadow mode always returns verdict='ok' to avoid surfacing
    potentially-wrong warnings; the real verdict is persisted to
    cairn_intel.quote_review_shadow for later review. Cutover
    scheduled 2026-05-13.
    """
    project_id = str(payload.get('project_id') or '').strip()
    total = payload.get('total_inc_vat')
    try:
        total_f = float(total) if total is not None else None
    except (TypeError, ValueError):
        total_f = None
    scope = str(payload.get('scope_summary') or '')
    line_items = str(payload.get('line_items_summary') or '')

    from core.intel.quote_context import review_draft_quote

    conn = _connect()
    try:
        result = review_draft_quote(
            project_id, total_f, scope, line_items, conn=conn,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return JSONResponse(result)
