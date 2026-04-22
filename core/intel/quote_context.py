"""Quote intelligence composition module.

Implements the read-only intelligence layer the CRM quote editor
calls for its sidebar and the /review sanity check.

Three public entry points:

  get_quote_context(project_id) -> dict
      Composite: client payment record, similar past jobs,
      margin statistics, lessons learned. Used by the sidebar.

  search_similar_quotes(query, limit) -> list[dict]
      Thin wrapper over CRM search scoped to project rows with
      quoted_amount populated — the "show me 5 quotes like this"
      button.

  review_draft_quote(project_id, total, summary) -> dict
      Margin / deposit / risk sanity check. Shadow-mode gated —
      returns verdict='ok' + logs when shadow is on; surfaces the
      real verdict after the 2026-05-13 cutover.

All three are pure-ish — they talk to the live CRM via HTTP and
to local Qwen via Ollama, but never mutate state. The only write
is shadow-log insertion, which is fire-and-forget.
"""
from __future__ import annotations

import json
import logging
import os
import re
import statistics
from dataclasses import dataclass
from typing import Any

import httpx


logger = logging.getLogger(__name__)


CRM_DEFAULT_BASE_URL = 'https://crm.nbnesigns.co.uk'
CRM_REQUEST_TIMEOUT = 10.0
CONTEXT_CACHE_TTL_SECONDS = 300

OLLAMA_DEFAULT_URL = 'http://localhost:11434'
OLLAMA_DEFAULT_MODEL = 'qwen2.5:7b-instruct'

# Signals thresholds — config not code once they stabilise.
MARGIN_BELOW_MEDIAN_FLAG_PCT = 25.0    # >25% below median is a flag
MARGIN_ABOVE_MEDIAN_FLAG_PCT = 40.0    # >40% above median is a flag
RECENT_LATE_PAYMENT_FLAG = 2           # 2+ late payments in record
MIN_SAMPLE_FOR_MARGIN = 3              # need 3+ samples to compute margin ref


# ── Auth helpers ─────────────────────────────────────────────────────

def _bearer_token() -> str:
    return (
        os.getenv('DEEK_API_KEY')
        or os.getenv('CAIRN_API_KEY')
        or os.getenv('CLAW_API_KEY', '')
    ).strip()


def _crm_base() -> str:
    return (os.getenv('CRM_BASE_URL') or CRM_DEFAULT_BASE_URL).rstrip('/')


# ── Context composition ─────────────────────────────────────────────

def get_quote_context(
    project_id: str,
    *,
    query: str | None = None,
    similar_limit: int = 5,
    lessons_limit: int = 3,
) -> dict:
    """Pull everything the quote editor sidebar should see for this
    project. Never raises — missing sections return empty structures
    so the CRM can render what's available.
    """
    project_id = (project_id or '').strip()
    if not project_id:
        return _empty_context('')

    token = _bearer_token()
    if not token:
        ctx = _empty_context(project_id)
        ctx['warnings'] = ['DEEK_API_KEY not set — CRM reads disabled']
        return ctx

    base = _crm_base()

    # 1. Project + client core. Uses CRM search as the primitive; if
    # a dedicated /projects/{id} endpoint becomes available later
    # we can swap it in without touching callers.
    project_row = _fetch_project_row(base, token, project_id)
    client_name = (project_row.get('client') or '').strip()
    project_name = (project_row.get('project_name') or '').strip()
    project_content = (project_row.get('content') or '').strip()

    # 2. Similar past jobs (reuse the Phase D primitive so ranking
    # stays consistent between sidebar + triage digest).
    similar_query = (query or project_content or project_name or client_name)
    similar_jobs: list[dict] = []
    try:
        from core.triage.similar_jobs import find_similar_jobs
        jobs = find_similar_jobs(
            similar_query,
            client_name=client_name or None,
            exclude_project_id=project_id,
            limit=similar_limit,
        )
        similar_jobs = [
            {
                'project_id': j.project_id,
                'project_name': j.project_name,
                'client_name': j.client_name,
                'quoted_amount': j.quoted_amount,
                'status': j.status,
                'summary': j.summary,
                'match_score': j.score,
                'has_local_folder': j.has_local_folder,
            }
            for j in jobs
        ]
    except Exception as exc:
        logger.warning('[quote_context] similar_jobs failed: %s', exc)

    # 3. Client payment record — aggregates from CRM search over
    # client-type rows. Until CRM exposes a dedicated risk endpoint
    # the metadata embedded in search results is our ground truth.
    client_block = _compose_client_block(
        base, token, project_row, client_name,
    )

    # 4. Margin reference — median + IQR over the quoted_amount
    # values we just gathered, plus any prior_quotes embedded in
    # client_block['prior_quotes'].
    margin_samples = [
        float(j['quoted_amount'])
        for j in similar_jobs
        if j.get('quoted_amount') is not None
    ]
    for pq in client_block.get('prior_quotes', []):
        amt = pq.get('total')
        if amt is not None:
            try:
                margin_samples.append(float(amt))
            except (TypeError, ValueError):
                continue
    margin_ref = _margin_reference(margin_samples)

    # 5. Lessons learned (retrieve_similar_decisions source_type='kb').
    lessons = _fetch_lessons(similar_query, lessons_limit)

    return {
        'project_id': project_id,
        'project_name': project_name,
        'query_used': similar_query,
        'client': client_block,
        'similar_jobs': similar_jobs,
        'margin_reference': margin_ref,
        'lessons_learned': lessons,
        'generated_at': _utcnow_iso(),
        'cache_ttl_seconds': CONTEXT_CACHE_TTL_SECONDS,
        'warnings': [],
    }


def _empty_context(project_id: str) -> dict:
    return {
        'project_id': project_id,
        'project_name': '',
        'query_used': '',
        'client': {
            'name': None,
            'payment_record': None,
            'prior_quotes': [],
        },
        'similar_jobs': [],
        'margin_reference': None,
        'lessons_learned': [],
        'generated_at': _utcnow_iso(),
        'cache_ttl_seconds': CONTEXT_CACHE_TTL_SECONDS,
        'warnings': [],
    }


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── CRM reads ───────────────────────────────────────────────────────

def _fetch_project_row(
    base: str, token: str, project_id: str,
) -> dict:
    """Locate the project row via search_crm. Returns the metadata
    bag + content on success, empty dict on any failure.

    Prefer a dedicated GET /api/cairn/projects/{id} once the CRM
    exposes one — tracked as a follow-up brief.
    """
    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            r = client.get(
                f'{base}/api/cairn/search',
                params={'q': project_id, 'types': 'project', 'limit': 5},
                headers={'Authorization': f'Bearer {token}'},
            )
        if r.status_code != 200:
            return {}
        data = r.json() or {}
        for row in data.get('results') or []:
            if (row.get('source_id') or '') == project_id:
                md = row.get('metadata') or {}
                return {
                    'project_id': project_id,
                    'project_name': md.get('project_name') or row.get('title') or '',
                    'client': md.get('client') or '',
                    'stage': md.get('stage'),
                    'value': md.get('value'),
                    'content': row.get('content') or '',
                    'metadata': md,
                }
    except Exception as exc:
        logger.warning('[quote_context] project fetch failed: %s', exc)
    return {}


def _compose_client_block(
    base: str, token: str, project_row: dict, client_name: str,
) -> dict:
    """Build the client.* nested structure. Pulls:
      * client_name (already in project_row)
      * payment_record — aggregated from CRM search on client rows
      * prior_quotes  — other projects this client has had with
                        quoted values
    """
    out: dict = {
        'name': client_name or None,
        'payment_record': None,
        'prior_quotes': [],
    }
    if not client_name:
        return out

    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            r = client.get(
                f'{base}/api/cairn/search',
                params={'q': client_name, 'types': 'client,project',
                        'limit': 15},
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        logger.warning('[quote_context] client block fetch failed: %s', exc)
        return out
    if r.status_code != 200:
        return out
    try:
        data = r.json() or {}
    except Exception:
        return out

    prior_quotes: list[dict] = []
    payment_hints: dict = {}
    for row in data.get('results') or []:
        st = row.get('source_type') or ''
        md = row.get('metadata') or {}
        content = (row.get('content') or '')[:500]
        if st == 'client':
            payment_hints = _extract_payment_hints(md, content)
        elif st == 'project':
            if (md.get('client') or '').strip().lower() != client_name.lower():
                continue
            if (row.get('source_id') or '') == project_row.get('project_id'):
                continue  # skip self
            value = md.get('value')
            if value is None:
                continue
            try:
                total = float(value)
            except (TypeError, ValueError):
                continue
            prior_quotes.append({
                'project_id': row.get('source_id'),
                'project_name': md.get('project_name') or row.get('title') or '',
                'total': total,
                'status': (md.get('stage') or '').lower() or None,
            })

    out['prior_quotes'] = prior_quotes
    if payment_hints:
        out['payment_record'] = payment_hints
    return out


_LATE_RE = re.compile(r'(\d+)\s*(?:late|overdue)\s*(?:payment|invoice)', re.IGNORECASE)
_DISPUTE_RE = re.compile(r'(\d+)\s*(?:dispute|chargeback)', re.IGNORECASE)
_RISK_BAND_RE = re.compile(r'risk\s*band[:\s]*(LOW|MEDIUM|HIGH|CRITICAL)', re.IGNORECASE)


def _extract_payment_hints(md: dict, content: str) -> dict:
    """Pull whatever the CRM client-row surfaces about payment
    behaviour. The CRM's CounterpartyRisk signals are embedded in
    search content; this is a best-effort extractor until the CRM
    exposes a dedicated /risk endpoint.
    """
    out: dict = {}
    # Metadata fields may carry these directly
    for key in ('risk_band', 'on_time_count', 'late_count',
                'disputed_count', 'total_quoted', 'quoted_value'):
        v = md.get(key)
        if v is not None:
            out[key] = v

    # Heuristic regex over content for anything missing
    if 'late_count' not in out:
        m = _LATE_RE.search(content)
        if m:
            out['late_count'] = int(m.group(1))
    if 'disputed_count' not in out:
        m = _DISPUTE_RE.search(content)
        if m:
            out['disputed_count'] = int(m.group(1))
    if 'risk_band' not in out:
        m = _RISK_BAND_RE.search(content)
        if m:
            out['risk_band'] = m.group(1).upper()

    return out or None  # type: ignore[return-value]


# ── Margin stats ────────────────────────────────────────────────────

def _margin_reference(samples: list[float]) -> dict | None:
    clean = [s for s in samples if s and s > 0]
    if len(clean) < MIN_SAMPLE_FOR_MARGIN:
        return None
    clean.sort()
    median = statistics.median(clean)
    # Simple 10th/90th pct for range — IQR on small N can collapse
    n = len(clean)
    low = clean[max(0, int(n * 0.1) - 1)]
    high = clean[min(n - 1, int(n * 0.9))]
    mean = statistics.mean(clean)
    return {
        'sample_size': n,
        'quoted_range_low': round(low, 2),
        'quoted_range_median': round(median, 2),
        'quoted_range_high': round(high, 2),
        'quoted_range_mean': round(mean, 2),
    }


# ── Lessons learned ─────────────────────────────────────────────────

def _fetch_lessons(query: str, limit: int) -> list[dict]:
    if not query:
        return []
    token = _bearer_token()
    if not token:
        return []
    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            r = client.get(
                f'{_crm_base()}/api/cairn/search',
                params={'q': query, 'types': 'kb', 'limit': limit},
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        logger.warning('[quote_context] lessons fetch failed: %s', exc)
        return []
    if r.status_code != 200:
        return []
    try:
        data = r.json() or {}
    except Exception:
        return []
    out = []
    for row in data.get('results') or []:
        md = row.get('metadata') or {}
        out.append({
            'id': row.get('source_id'),
            'title': md.get('title') or row.get('title') or '',
            'summary_short': (row.get('content') or '')[:300],
            'relevance_score': round(float(row.get('score') or 0.0), 3),
        })
    return out[:limit]


# ── Similar quotes thin wrapper ─────────────────────────────────────

def search_similar_quotes(query: str, limit: int = 5) -> list[dict]:
    """Thin search_crm wrapper scoped to projects with quoted
    values. Returns the "5 quotes like this" list."""
    query = (query or '').strip()
    if not query:
        return []
    token = _bearer_token()
    if not token:
        return []
    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            r = client.get(
                f'{_crm_base()}/api/cairn/search',
                params={'q': query, 'types': 'project,quote',
                        'limit': max(1, min(int(limit), 20))},
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        logger.warning('[quote_context] similar_quotes failed: %s', exc)
        return []
    if r.status_code != 200:
        return []
    try:
        data = r.json() or {}
    except Exception:
        return []
    out = []
    for row in data.get('results') or []:
        md = row.get('metadata') or {}
        value = md.get('value')
        try:
            total = float(value) if value is not None else None
        except (TypeError, ValueError):
            total = None
        out.append({
            'project_id': row.get('source_id'),
            'project_name': md.get('project_name') or row.get('title') or '',
            'client_name': md.get('client'),
            'total': total,
            'status': (md.get('stage') or '').lower() or None,
            'line_item_preview': (row.get('content') or '')[:250],
            'match_score': round(float(row.get('score') or 0.0), 3),
        })
    return out


# ── Review / sanity check ───────────────────────────────────────────

_REVIEW_SYSTEM = """You are a quote reviewer for NBNE Signs. Given
a drafted quote (total, scope summary, line items summary) and
historical context (similar past quotes, client payment record,
margin reference, relevant lessons), return a JSON verdict on
whether this quote looks reasonable.

Output ONLY a single JSON object:

  {
    "verdict": "ok" | "investigate" | "flag",
    "reasoning": "<one-sentence, user-facing>",
    "signals": ["<short signal>", ...]
  }

Rubric:
  ok           — within typical margins, client is fine, no red flags
  investigate  — 1 mild anomaly worth a second look
  flag         — clear problem: way below typical, client has payment
                 history, scope mismatch with historical patterns

Do NOT invent context not present in the input. Keep reasoning
short and plain-English. Signals should be 3-8 words each.
"""


def review_draft_quote(
    project_id: str,
    total_inc_vat: float | None,
    scope_summary: str = '',
    line_items_summary: str = '',
    *,
    conn=None,
    shadow_override: bool | None = None,
) -> dict:
    """Sanity-check a drafted quote. Shadow-mode gated by
    DEEK_QUOTE_REVIEW_SHADOW (default true) until cutover fires
    on 2026-05-13.

    In shadow mode the verdict is computed + logged but the API
    returns verdict='ok' regardless, so the CRM UI doesn't yet
    surface wrong-looking warnings. `conn` is required to write
    the shadow log; when absent, logging is skipped (never
    raises). `shadow_override` lets tests bypass the env var.
    """
    shadow = (
        shadow_override
        if shadow_override is not None
        else is_quote_review_shadow()
    )

    ctx = get_quote_context(project_id) if project_id else _empty_context('')
    # Compute deterministic signals first — Qwen refines reasoning
    # but the signal list is the audit trail.
    signals = _compute_signals(ctx, total_inc_vat, scope_summary)

    # LLM call — small context, cheap.
    qwen_verdict = _qwen_quote_review(
        ctx, total_inc_vat, scope_summary, line_items_summary, signals,
    )
    real_verdict = qwen_verdict or {
        'verdict': 'ok' if not signals else 'investigate',
        'reasoning': (
            'No historical context to compare against.'
            if not ctx.get('margin_reference') else
            'Deterministic signal check produced no flag-level issues.'
        ),
    }
    real_verdict['signals'] = signals

    # Persist to shadow table regardless of shadow mode (so Toby
    # can review accuracy even post-cutover).
    if conn is not None:
        try:
            _log_shadow(
                conn,
                project_id=project_id,
                total_inc_vat=total_inc_vat,
                verdict=real_verdict['verdict'],
                reasoning=real_verdict.get('reasoning', ''),
                signals=signals,
                context_used=_truncate_context(ctx),
            )
        except Exception as exc:
            logger.warning('[quote_context] shadow log failed: %s', exc)

    if shadow:
        return {
            'verdict': 'ok',
            'reasoning': 'Quote review in shadow mode; no user-visible warnings yet.',
            'signals': [],
            'shadow_mode': True,
            'shadow_verdict': real_verdict['verdict'],
        }
    return {**real_verdict, 'shadow_mode': False}


def _compute_signals(
    ctx: dict, total_inc_vat: float | None, scope_summary: str,
) -> list[str]:
    signals: list[str] = []
    margin = ctx.get('margin_reference') or {}
    if total_inc_vat is not None and margin.get('quoted_range_median'):
        median = float(margin['quoted_range_median'])
        if median > 0:
            delta_pct = (total_inc_vat - median) / median * 100.0
            if delta_pct < -MARGIN_BELOW_MEDIAN_FLAG_PCT:
                signals.append(
                    f'margin_vs_median: {delta_pct:+.0f}% (below)'
                )
            elif delta_pct > MARGIN_ABOVE_MEDIAN_FLAG_PCT:
                signals.append(
                    f'margin_vs_median: {delta_pct:+.0f}% (above)'
                )

    # Client payment record
    payment = (ctx.get('client') or {}).get('payment_record') or {}
    late = payment.get('late_count')
    if late is not None and int(late) >= RECENT_LATE_PAYMENT_FLAG:
        signals.append(f'client_late_payments: {int(late)}')
    risk_band = (payment.get('risk_band') or '').upper()
    if risk_band in ('HIGH', 'CRITICAL'):
        signals.append(f'counterparty_risk_band: {risk_band}')

    # Install-keyword present in scope but no "install" line mention
    low_scope = (scope_summary or '').lower()
    if any(kw in low_scope for kw in ('install', 'fit', 'fix')):
        if 'install' not in low_scope:
            # heuristic; the presence of fit/fix but no 'install'
            # doesn't actually prove anything missing. Skipping the
            # signal until line-item data is plumbed through.
            pass

    return signals


def _truncate_context(ctx: dict) -> dict:
    """Keep the shadow log compact — full context can be big."""
    return {
        'project_id': ctx.get('project_id'),
        'margin_reference': ctx.get('margin_reference'),
        'similar_jobs_count': len(ctx.get('similar_jobs') or []),
        'client_name': (ctx.get('client') or {}).get('name'),
        'payment_record': (ctx.get('client') or {}).get('payment_record'),
        'lessons_count': len(ctx.get('lessons_learned') or []),
    }


def _qwen_quote_review(
    ctx: dict, total: float | None, scope: str, line_items: str,
    signals: list[str],
) -> dict | None:
    """Call local Qwen for the narrative verdict. None on failure
    — caller falls back to a deterministic default."""
    base = (os.getenv('OLLAMA_BASE_URL') or OLLAMA_DEFAULT_URL).rstrip('/')
    model = os.getenv('OLLAMA_QUOTE_REVIEW_MODEL') or OLLAMA_DEFAULT_MODEL

    user = json.dumps({
        'total_inc_vat': total,
        'scope_summary': scope[:600],
        'line_items_summary': line_items[:600],
        'signals_pre_computed': signals,
        'margin_reference': ctx.get('margin_reference'),
        'client': {
            'name': (ctx.get('client') or {}).get('name'),
            'payment_record': (ctx.get('client') or {}).get('payment_record'),
            'prior_quotes_count': len((ctx.get('client') or {}).get('prior_quotes') or []),
        },
        'similar_jobs': (ctx.get('similar_jobs') or [])[:3],
    }, indent=2, default=str)

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': _REVIEW_SYSTEM},
            {'role': 'user', 'content': user},
        ],
        'stream': False,
        'format': 'json',
        'options': {'temperature': 0.1, 'num_ctx': 4096},
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(f'{base}/api/chat', json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning('[quote_context] qwen review failed: %s', exc)
        return None

    content = (data.get('message') or {}).get('content') or ''
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Strip fences as a last-resort
        stripped = re.sub(r'^```(?:json)?\s*|\s*```$', '', content.strip(), flags=re.DOTALL)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None

    verdict = str(parsed.get('verdict') or '').strip().lower()
    if verdict not in {'ok', 'investigate', 'flag'}:
        return None
    reasoning = str(parsed.get('reasoning') or '').strip()[:400]
    return {'verdict': verdict, 'reasoning': reasoning}


def _log_shadow(
    conn, *, project_id: str, total_inc_vat: float | None,
    verdict: str, reasoning: str, signals: list[str],
    context_used: dict,
) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO cairn_intel.quote_review_shadow
                (project_id, total_inc_vat, verdict, reasoning,
                 signals, context_used, created_at)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
               RETURNING id""",
            (project_id, total_inc_vat, verdict, reasoning,
             json.dumps(signals), json.dumps(context_used, default=str)),
        )
        row = cur.fetchone()
        conn.commit()
        return int(row[0]) if row else None


# ── Shadow gate ─────────────────────────────────────────────────────

def is_quote_review_shadow() -> bool:
    """Default: shadow-on until the 2026-05-13 cutover cron flips
    DEEK_QUOTE_REVIEW_SHADOW to false in the env file."""
    raw = (os.getenv('DEEK_QUOTE_REVIEW_SHADOW') or 'true').strip().lower()
    return raw in {'true', '1', 'yes', 'on'}


__all__ = [
    'get_quote_context',
    'search_similar_quotes',
    'review_draft_quote',
    'is_quote_review_shadow',
]
