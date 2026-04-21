"""Fetch a short project history block for the response drafter.

Given a match candidate from project_matcher, pull the CRM's
summary + most recent activity via the same /api/cairn/search
endpoint we use for matching. Output is a ~1-2 KB text block the
drafter uses to ground its reply.

Kept intentionally thin — the drafter does the heavy lifting. This
just feeds it the facts.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)


CRM_DEFAULT_BASE_URL = 'https://crm.nbnesigns.co.uk'
CRM_SEARCH_PATH = '/api/cairn/search'
CRM_REQUEST_TIMEOUT = 10.0
HISTORY_ITEMS_LIMIT = 6      # past quotes / emails / notes to surface
HISTORY_TEXT_CAP_CHARS = 2200  # hard cap on returned block


def fetch_project_history(
    candidate: dict | None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Return a formatted history block for the candidate project.

    Empty string on any failure or when the candidate has no
    project_id — the drafter handles empty history gracefully.
    """
    if not candidate:
        return ''
    project_id = candidate.get('project_id') or ''
    project_name = candidate.get('project_name') or ''
    if not project_id and not project_name:
        return ''

    base = (base_url or os.getenv('CRM_BASE_URL') or CRM_DEFAULT_BASE_URL).rstrip('/')
    token = api_key or (
        os.getenv('DEEK_API_KEY')
        or os.getenv('CAIRN_API_KEY')
        or os.getenv('CLAW_API_KEY', '')
    ).strip()
    if not token:
        return ''

    # Query the CRM for everything linked to this project — quotes,
    # emails, notes, lessons. The matcher only returned `project` and
    # `client` types; here we widen to include quote + email + kb.
    query = (project_name or project_id)[:200]
    try:
        with httpx.Client(timeout=CRM_REQUEST_TIMEOUT) as client:
            response = client.get(
                f'{base}{CRM_SEARCH_PATH}',
                params={
                    'q': query,
                    'types': 'project,quote,email,kb',
                    'limit': HISTORY_ITEMS_LIMIT,
                },
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        log.debug('[project_history] CRM fetch failed: %s', exc)
        return ''

    if response.status_code != 200:
        log.debug(
            '[project_history] CRM HTTP %d — %s',
            response.status_code, response.text[:200],
        )
        return ''

    try:
        data = response.json()
    except Exception:
        return ''

    results = data.get('results') or []
    if not results:
        return ''

    lines: list[str] = []
    # Put the primary project row first (it carries the summary), then
    # other items ordered by whatever the CRM returned.
    primary = [r for r in results if r.get('source_id') == project_id]
    rest = [r for r in results if r.get('source_id') != project_id]
    for r in primary + rest:
        md = r.get('metadata') or {}
        kind = r.get('source_type', '').upper()
        title = (
            md.get('title')
            or md.get('project_name')
            or r.get('title')
            or '(untitled)'
        )
        when = md.get('created_at') or md.get('updated_at') or ''
        excerpt = (r.get('excerpt') or '').strip()
        if not excerpt:
            continue
        header = f'[{kind}] {title}'
        if when:
            header += f' ({when[:10]})'
        lines.append(header)
        lines.append(excerpt[:400])
        lines.append('')

    block = '\n'.join(lines).strip()
    if len(block) > HISTORY_TEXT_CAP_CHARS:
        block = block[:HISTORY_TEXT_CAP_CHARS - 3].rstrip() + '...'
    return block


__all__ = ['fetch_project_history']
