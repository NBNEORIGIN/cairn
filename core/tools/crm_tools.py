"""
CRM chat tool — live hybrid search over the NBNE CRM knowledge layer.

The CRM at ``crm.nbnesigns.co.uk`` maintains its own pgvector HNSW +
tsvector index (``crm_embeddings`` table) covering projects, clients,
materials, quotes, emails and LessonLearned rows. Instead of
duplicating all that data into ``cairn_intel``, this tool proxies a
live hybrid-search HTTP call into the CRM's own ``/api/cairn/search``
endpoint and formats the results for the chat loop.

Auth:
    Server-to-server via a Bearer token matching ``DEEK_API_KEY`` —
    same token on both sides, enforced by the CRM's middleware.ts.
    See NBNEORIGIN/crm commit 3d052cd.

Config:
    DEEK_API_KEY    — shared bearer (required; empty disables the tool)
    CRM_BASE_URL     — default https://crm.nbnesigns.co.uk

Source types the tool can filter by (mirrors
``D:/crm/lib/cairn-indexer.ts``):

    project   — Pipeline items (Project Prisma model)
    client    — Contact records (Client + ClientBusiness)
    material  — Stock / COGS (Material)
    kb        — LessonLearned (structured post-mortems)
    quote     — Quote content
    email     — Indexed email subjects + bodies

Matches the shape of the existing ``search_wiki`` / ``search_emails``
tools in deek_tools.py so the chat loop handles it identically.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from .registry import Tool, RiskLevel


CRM_DEFAULT_BASE_URL = 'https://crm.nbnesigns.co.uk'
CRM_SEARCH_PATH = '/api/cairn/search'
CRM_REQUEST_TIMEOUT = 10.0  # seconds


def _search_crm(
    project_root: str,
    query: str,
    limit: int = 5,
    types: list[str] | str | None = None,
    **kwargs,
) -> str:
    """Tool entry point.

    ``types`` can be a list like ``['kb', 'project']`` or a single
    comma-separated string like ``"kb,project"`` — the CRM endpoint
    accepts a comma-separated ``types=`` query param.
    """
    try:
        limit = int(limit)
    except Exception:
        limit = 5
    limit = max(1, min(limit, 20))

    token = (os.getenv('DEEK_API_KEY') or os.getenv('CAIRN_API_KEY') or os.getenv('CLAW_API_KEY', '')).strip()
    if not token:
        return (
            'CRM search unavailable: DEEK_API_KEY is not set. '
            'This tool calls the CRM server-to-server with a shared '
            'token — set DEEK_API_KEY in the deek-api env to enable.'
        )

    base_url = os.getenv('CRM_BASE_URL', CRM_DEFAULT_BASE_URL).rstrip('/')

    # Normalise `types` into a CSV string the CRM endpoint expects.
    types_csv: str | None = None
    if isinstance(types, list):
        types_csv = ','.join(t.strip() for t in types if isinstance(t, str) and t.strip())
    elif isinstance(types, str) and types.strip():
        types_csv = types.strip()

    params: dict[str, Any] = {'q': query, 'limit': limit}
    if types_csv:
        params['types'] = types_csv

    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            response = client.get(
                f'{base_url}{CRM_SEARCH_PATH}',
                params=params,
                headers={'Authorization': f'Bearer {token}'},
            )
    except httpx.TimeoutException:
        return f'CRM search timed out after {CRM_REQUEST_TIMEOUT:.0f}s — CRM may be slow or unreachable.'
    except Exception as exc:
        return f'CRM search failed: {type(exc).__name__}: {exc}'

    if response.status_code == 401:
        return (
            'CRM search unauthorized: the Bearer token in DEEK_API_KEY '
            'was rejected by the CRM middleware. Check that the token '
            'on this side matches the DEEK_API_KEY in the CRM container.'
        )
    if response.status_code == 429:
        return 'CRM search rate-limited (429) — retry in a moment.'
    if response.status_code >= 500:
        return f'CRM search: server error {response.status_code} from {base_url}.'
    if response.status_code != 200:
        return f'CRM search: unexpected HTTP {response.status_code} from {base_url}.'

    try:
        data = response.json()
    except Exception as exc:
        return f'CRM search: could not parse response body ({exc})'

    results = data.get('results') or []
    if not results:
        return (
            f'No CRM results for: {query}\n'
            f'Searched source types: {types_csv or "all (project, client, material, kb, quote, email)"}'
        )

    lines = [f'Top {len(results)} CRM results for: {query}', '']
    for result in results:
        score = result.get('score')
        source_type = result.get('source_type', 'unknown')
        content = (result.get('content') or '').strip()
        metadata = result.get('metadata') or {}
        method = result.get('retrieval_method', '')

        score_txt = f'{score:.3f}' if isinstance(score, (int, float)) else 'n/a'
        header = f'[{score_txt}] {source_type}'
        if method:
            header += f' ({method})'
        lines.append(header)

        # Pull a few useful metadata fields to surface alongside the content
        meta_bits: list[str] = []
        for key in ('project_name', 'client', 'stage', 'value', 'title', 'category', 'name', 'subject', 'from'):
            val = metadata.get(key)
            if val not in (None, '', []):
                meta_bits.append(f'{key}: {val}')
        if meta_bits:
            lines.append('  ' + ' | '.join(meta_bits))

        compact = ' '.join(content.split())
        if len(compact) > 350:
            compact = compact[:350] + '...'
        if compact:
            lines.append(f'  {compact}')
        lines.append('')

    return '\n'.join(lines).rstrip()


# ── Write tools ───────────────────────────────────────────────────────
#
# The CRM today exposes three write surfaces under /api/cairn/*:
#
#   POST   /api/cairn/memory                — create a recommendation,
#                                              observation, or alert
#                                              (writes cairn_recommendations)
#   PATCH  /api/cairn/memory                — mark a recommendation actioned
#   PATCH  /api/cairn/projects/{id}/folder  — set localFolderPath
#                                              (Phase C endpoint; may 404 if
#                                              CRM-side PR not merged)
#
# Richer writes (add note to a project, update project stage/value,
# create a client) will come via the CRM spanning brief
# `briefs/crm-write-endpoints.md`. Until those land, this tool set
# covers the most common thing Toby would ask Deek to persist:
# "remember that <observation>" against the recommendations table.

CRM_MEMORY_PATH = '/api/cairn/memory'
CRM_PROJECT_FOLDER_PATH = '/api/cairn/projects/{id}/folder'

_MEMORY_TYPES = {'recommendation', 'observation', 'alert'}
_PRIORITIES = {'high', 'medium', 'low'}


def _bearer_token() -> str:
    return (
        os.getenv('DEEK_API_KEY')
        or os.getenv('CAIRN_API_KEY')
        or os.getenv('CLAW_API_KEY', '')
    ).strip()


def _crm_base() -> str:
    return (os.getenv('CRM_BASE_URL') or CRM_DEFAULT_BASE_URL).rstrip('/')


def _write_crm_memory(
    project_root: str,
    message: str,
    type: str = 'observation',
    priority: str = 'medium',
    project_id: str | None = None,
    **kwargs,
) -> str:
    """Write a recommendation / observation / alert to the CRM.

    Wraps ``POST /api/cairn/memory``. Surfaces in the CRM's Live
    Recommendations panel and is searchable via search_crm.
    """
    # Keep a handle to the builtin because the ``type`` parameter
    # shadows it inside this function.
    _exc_type = __builtins__.get('type') if isinstance(__builtins__, dict) else __builtins__.type  # type: ignore[attr-defined]

    message = (message or '').strip()
    if not message:
        return "write_crm_memory error: 'message' is required."
    mem_type = (type or 'observation').strip().lower()
    if mem_type not in _MEMORY_TYPES:
        return (
            f"write_crm_memory error: 'type' must be one of "
            f"{sorted(_MEMORY_TYPES)}; got {mem_type!r}"
        )
    priority = (priority or 'medium').strip().lower()
    if priority not in _PRIORITIES:
        return (
            f"write_crm_memory error: 'priority' must be one of "
            f"{sorted(_PRIORITIES)}; got {priority!r}"
        )
    token = _bearer_token()
    if not token:
        return 'write_crm_memory error: DEEK_API_KEY is not set.'

    payload: dict[str, Any] = {
        'type': mem_type,
        'priority': priority,
        'message': message[:3000],
        'source_modules': ['deek', 'chat'],
    }
    if project_id:
        payload['project_id'] = str(project_id)

    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            r = client.post(
                f'{_crm_base()}{CRM_MEMORY_PATH}',
                json=payload,
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        return f'write_crm_memory error: {_exc_type(exc).__name__}: {exc}'

    if r.status_code not in (200, 201):
        return (
            f'write_crm_memory error: CRM returned HTTP {r.status_code}: '
            f'{r.text[:300]}'
        )
    try:
        data = r.json() or {}
    except Exception:
        data = {}
    rec_id = data.get('id') or '?'
    return (
        f'Wrote CRM {mem_type} (id={rec_id}, priority={priority}'
        + (f', project={project_id}' if project_id else '')
        + f'): {message[:200]}'
        + ('…' if len(message) > 200 else '')
    )


def _mark_crm_actioned(
    project_root: str,
    recommendation_id: str,
    actioned_by: str = 'deek',
    **kwargs,
) -> str:
    """Mark a CRM recommendation actioned. Wraps ``PATCH /api/cairn/memory``.
    """
    recommendation_id = (recommendation_id or '').strip()
    if not recommendation_id:
        return "mark_crm_actioned error: 'recommendation_id' is required."
    token = _bearer_token()
    if not token:
        return 'mark_crm_actioned error: DEEK_API_KEY is not set.'
    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            r = client.patch(
                f'{_crm_base()}{CRM_MEMORY_PATH}',
                json={
                    'id': recommendation_id,
                    'actioned_by': actioned_by or 'deek',
                },
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        return f'mark_crm_actioned error: {type(exc).__name__}: {exc}'
    if r.status_code == 404:
        return f'mark_crm_actioned: recommendation {recommendation_id} not found.'
    if r.status_code not in (200, 201):
        return (
            f'mark_crm_actioned error: CRM returned HTTP {r.status_code}: '
            f'{r.text[:300]}'
        )
    return f'Marked CRM recommendation {recommendation_id} actioned by {actioned_by}.'


def _set_crm_project_folder(
    project_root: str,
    project_id: str,
    folder_path: str,
    **kwargs,
) -> str:
    """Set a project's localFolderPath. Wraps
    ``PATCH /api/cairn/projects/{id}/folder`` (Phase C endpoint).

    Returns a user-visible string describing the outcome. If the
    CRM hasn't deployed the Phase C endpoint yet (404/405) the tool
    says so explicitly rather than silently failing.
    """
    project_id = (project_id or '').strip()
    folder_path = (folder_path or '').strip()
    if not project_id:
        return "set_crm_project_folder error: 'project_id' is required."
    if not folder_path:
        return "set_crm_project_folder error: 'folder_path' is required."
    token = _bearer_token()
    if not token:
        return 'set_crm_project_folder error: DEEK_API_KEY is not set.'
    url = f"{_crm_base()}{CRM_PROJECT_FOLDER_PATH.format(id=project_id)}"
    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            r = client.patch(
                url,
                json={'localFolderPath': folder_path[:500]},
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        return f'set_crm_project_folder error: {type(exc).__name__}: {exc}'
    if r.status_code in (404, 405):
        return (
            'set_crm_project_folder: CRM endpoint not available yet '
            '(Phase C PR not merged). Fall back to write_crm_memory '
            'with the path in the message so it still gets captured.'
        )
    if r.status_code not in (200, 201, 204):
        return (
            f'set_crm_project_folder error: CRM returned HTTP '
            f'{r.status_code}: {r.text[:300]}'
        )
    return (
        f'Set project {project_id} folder to {folder_path}.'
    )


write_crm_memory_tool = Tool(
    name='write_crm_memory',
    description=(
        'Write a recommendation, observation, or alert into the CRM '
        'knowledge base. Persists to the cairn_recommendations table; '
        'appears in the CRM Live Recommendations panel and is '
        'searchable by search_crm thereafter. Use this when the user '
        'tells you something worth persisting about a project, client, '
        'or operational observation — e.g. "remember that Julie '
        "prefers callbacks after 3pm\", \"flag that the Mitre QR codes "
        'had duplicates", "recommend we revisit the Bamburgh quote". '
        'Arguments: message (required, free text — the observation), '
        "type (default 'observation'; use 'recommendation' when you're "
        "proposing an action, 'alert' for urgent issues), "
        "priority ('low' | 'medium' (default) | 'high'), project_id "
        '(optional — attach to a specific CRM project so it appears on '
        'that project\'s page).'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_write_crm_memory,
    required_permission='write_crm_memory',
)


mark_crm_actioned_tool = Tool(
    name='mark_crm_actioned',
    description=(
        'Mark a CRM recommendation as actioned (clears it from the '
        'Live Recommendations panel). Use when the user says a '
        'recommendation has been handled, or when the recommendation '
        'becomes irrelevant. Arguments: recommendation_id (required, '
        'the UUID returned by write_crm_memory or GET /api/cairn/memory), '
        "actioned_by (default 'deek')."
    ),
    risk_level=RiskLevel.SAFE,
    fn=_mark_crm_actioned,
    required_permission='mark_crm_actioned',
)


set_crm_project_folder_tool = Tool(
    name='set_crm_project_folder',
    description=(
        "Set a CRM project's localFolderPath — the absolute disk path "
        'where that project\'s working files live on the office '
        'workstation. Use when the user tells you where a project '
        "lives (e.g. \"the Julie job is at D:\\\\NBNE\\\\Projects\\\\M1234-julie\"). "
        'Falls back gracefully if the CRM endpoint is not yet '
        'deployed. Arguments: project_id (required), folder_path '
        '(required, max 500 chars).'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_set_crm_project_folder,
    required_permission='set_crm_project_folder',
)


# ── Quote intelligence tools ──────────────────────────────────────────
#
# Chat-tier wrappers around the /api/deek/quotes/* endpoints so the
# user can ask "what have we quoted for jobs like this?" in chat
# without opening the CRM.

def _quote_context_tool(
    project_root: str,
    project_id: str,
    query: str | None = None,
    **kwargs,
) -> str:
    """Agent tool: composite quote context for a project.

    Returns a compact formatted summary — client payment record,
    similar past jobs, margin stats, relevant lessons. Caller can
    quote numbers back to the user verbatim.
    """
    if not (project_id or '').strip():
        return "quote_context error: 'project_id' is required."
    try:
        from core.intel.quote_context import get_quote_context
        ctx = get_quote_context(project_id, query=query or None)
    except Exception as exc:
        return f'quote_context error: {exc.__class__.__name__}: {exc}'

    lines: list[str] = []
    lines.append(f"Quote context for project {ctx.get('project_id')}")
    if ctx.get('project_name'):
        lines.append(f"  project: {ctx['project_name']}")

    client = ctx.get('client') or {}
    if client.get('name'):
        lines.append(f"  client:  {client['name']}")
    pr = client.get('payment_record') or {}
    if pr:
        bits = [f'{k}={v}' for k, v in pr.items() if v is not None]
        lines.append(f"  payment: {' · '.join(bits)}")
    prior = client.get('prior_quotes') or []
    if prior:
        lines.append(f"  prior_quotes: {len(prior)} found")
        for pq in prior[:3]:
            amt = pq.get('total')
            amt_s = f"£{amt:,.0f}" if amt else '?'
            lines.append(
                f"    - {pq.get('project_name') or '?'} "
                f"[{pq.get('status') or '?'}] {amt_s}"
            )

    mr = ctx.get('margin_reference')
    if mr:
        lines.append(
            f"  margin reference (n={mr['sample_size']}): "
            f"low £{mr['quoted_range_low']:,.0f} · "
            f"med £{mr['quoted_range_median']:,.0f} · "
            f"high £{mr['quoted_range_high']:,.0f}"
        )
    else:
        lines.append('  margin reference: (insufficient sample)')

    sj = ctx.get('similar_jobs') or []
    if sj:
        lines.append(f"  similar jobs ({len(sj)}):")
        for j in sj[:5]:
            amt = j.get('quoted_amount')
            amt_s = f"£{amt:,.0f}" if amt else '?'
            lines.append(
                f"    - {j.get('project_name') or '?'}  "
                f"[{j.get('status') or '?'}]  {amt_s}  "
                f"match {j.get('match_score', 0):.2f}"
            )

    lessons = ctx.get('lessons_learned') or []
    if lessons:
        lines.append(f"  lessons: {len(lessons)}")
        for L in lessons[:3]:
            lines.append(f"    - {L.get('title') or '?'}")

    warnings = ctx.get('warnings') or []
    for w in warnings:
        lines.append(f"  ! {w}")

    return '\n'.join(lines)


def _similar_quotes_tool(
    project_root: str,
    query: str,
    limit: int = 5,
    **kwargs,
) -> str:
    if not (query or '').strip():
        return "search_similar_quotes error: 'query' is required."
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5
    try:
        from core.intel.quote_context import search_similar_quotes
        rows = search_similar_quotes(query, limit=limit)
    except Exception as exc:
        return f'search_similar_quotes error: {exc.__class__.__name__}'
    if not rows:
        return 'No similar quotes found.'
    out = [f'Top {len(rows)} similar projects/quotes:']
    for r in rows:
        amt = r.get('total')
        amt_s = f"£{amt:,.0f}" if amt else '?'
        out.append(
            f"  - {r.get('project_name') or '?'} "
            f"[{r.get('status') or '?'}] {amt_s}  "
            f"(match {r.get('match_score', 0):.2f})  "
            f"client: {r.get('client_name') or '?'}"
        )
        preview = (r.get('line_item_preview') or '').strip()
        if preview:
            out.append(f"    | {preview[:150]}")
    return '\n'.join(out)


def _review_quote_tool(
    project_root: str,
    project_id: str,
    total_inc_vat: float,
    scope_summary: str = '',
    line_items_summary: str = '',
    **kwargs,
) -> str:
    if not (project_id or '').strip():
        return "review_quote error: 'project_id' is required."
    try:
        total_f = float(total_inc_vat)
    except (TypeError, ValueError):
        return "review_quote error: 'total_inc_vat' must be a number."
    try:
        from core.intel.quote_context import review_draft_quote
        # Note: chat tool path does not pass a conn — shadow logs
        # skipped from chat-initiated review calls. The CRM editor
        # path through the HTTP endpoint does log, which is where
        # the real signal comes from.
        result = review_draft_quote(
            project_id, total_f, scope_summary, line_items_summary,
        )
    except Exception as exc:
        return f'review_quote error: {exc.__class__.__name__}: {exc}'

    verdict = result.get('verdict', 'ok')
    reasoning = result.get('reasoning') or '(no reasoning)'
    signals = result.get('signals') or []
    shadow = result.get('shadow_mode')
    shadow_v = result.get('shadow_verdict')

    out = [f'Verdict: {verdict.upper()}']
    out.append(f'Reasoning: {reasoning}')
    if signals:
        out.append('Signals:')
        for s in signals:
            out.append(f'  - {s}')
    if shadow:
        out.append(
            f"(Shadow mode; real verdict would be '{shadow_v}' — "
            'review surface gated until 2026-05-13 cutover.)'
        )
    return '\n'.join(out)


quote_context_tool = Tool(
    name='get_quote_context',
    description=(
        'Return composite quote-drafting context for a CRM project: '
        'the client\'s payment record + prior quotes, similar past '
        'jobs with their quoted amounts and outcomes, a margin '
        'reference (median + range) over comparable quotes, and any '
        'relevant LessonLearned rows. Use this when the user asks '
        '"what have we quoted for similar jobs?", or is about to '
        'draft a quote and wants context. Arguments: project_id '
        '(required), query (optional — overrides the auto-derived '
        'search text).'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_quote_context_tool,
    required_permission='get_quote_context',
)


similar_quotes_tool = Tool(
    name='search_similar_quotes',
    description=(
        'Find CRM projects / quotes that look like a free-text '
        'description. Thin hybrid-search wrapper scoped to project + '
        'quote rows. Use for "show me 5 quotes that look like this" '
        'style questions. Arguments: query (free text, required), '
        'limit (default 5, max 20).'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_similar_quotes_tool,
    required_permission='search_similar_quotes',
)


review_quote_tool = Tool(
    name='review_quote_draft',
    description=(
        'Sanity-check a drafted quote against historical patterns. '
        'Returns a verdict (ok / investigate / flag) with reasoning '
        'and signals (margin delta vs median, client payment risk, '
        'etc.). Shadow-mode-gated until 2026-05-13 — during shadow '
        'the verdict returned is always "ok" and the real verdict '
        'is noted in shadow_verdict. Arguments: project_id '
        '(required), total_inc_vat (required, £), scope_summary '
        '(optional), line_items_summary (optional).'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_review_quote_tool,
    required_permission='review_quote_draft',
)


search_crm_tool = Tool(
    name='search_crm',
    description=(
        'Search the NBNE CRM knowledge base — pipeline projects, client '
        'records, materials / stock, quotes, emails, and structured '
        'LessonLearned post-mortems. Runs a live hybrid pgvector + '
        'tsvector search against the CRM at crm.nbnesigns.co.uk. '
        'Use this whenever the user asks about a specific client, a '
        'project status, a quote history, what materials we use, or '
        '"have we learned this before?" style questions. '
        'Arguments: query (free text), limit (default 5, max 20), '
        "types (optional list/CSV — 'project', 'client', 'material', "
        "'kb' for lessons, 'quote', 'email'). "
        'Results are ranked by Reciprocal Rank Fusion over cosine and '
        'BM25 scores — higher is better. Always fresh; no cache lag. '
        "For 'have we been here before' questions about historical "
        'decisions, prefer retrieve_similar_decisions first (which '
        'pulls from the counterfactual memory spanning disputes, '
        'b2b_quotes, principles, and CRM lessons), then search_crm '
        'for live client/project context.'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_search_crm,
    required_permission='search_crm',
)
