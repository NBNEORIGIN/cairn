"""
Claude Haiku wrapper for context summarisation and archetype tagging.

Two jobs:
    1. ``summarise(raw_text)``  — distil a raw source record (email
       thread, m_number narrative, xero P&L month) into 3–5 sentences
       that will become ``decisions.context_summary``.
    2. ``tag(summary)``          — pick 2–4 archetype tags from the
       fixed taxonomy. The taxonomy must NOT be extended here —
       changes go through a dedicated re-tagging pass per the brief.

Budget is enforced by ``LLMBudget``. Every call increments
``bulk_used`` — Haiku is cheap but a runaway loop is still worth
catching.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .llm_budget import LLMBudget


# Canonical taxonomy — do NOT extend without a re-tagging pass.
ARCHETYPES = [
    'adversarial',
    'cooperative',
    'time_pressured',
    'information_asymmetric',
    'repeated_game',
    'one_shot',
    'pricing',
    'operational',
]


_SUMMARISE_SYSTEM = (
    'You are a concise business analyst. Your job is to summarise a '
    'historical business record into 3 to 5 sentences that preserve '
    'the structural details of the decision: who was involved, what '
    'was at stake, what constraints applied, and what was ultimately '
    'chosen. Do not add commentary. Do not speculate. Return the '
    'summary only, no preamble.'
)


_TAG_SYSTEM = (
    'You are a taxonomy classifier. Given a short business decision '
    "summary, return a JSON array of 2 to 4 archetype tags from this "
    "EXACT closed list — do not invent new tags:\n\n"
    '  adversarial          — negotiation with an opposing party\n'
    '  cooperative          — collaborative arrangement\n'
    '  time_pressured       — decision had a deadline or was reactive\n'
    '  information_asymmetric — one side knew things the other did not\n'
    '  repeated_game        — ongoing relationship, reputation matters\n'
    '  one_shot             — transactional, no repeat\n'
    '  pricing              — decision was about price, margin or terms\n'
    '  operational          — how to execute, rather than whether to\n\n'
    'Return JSON only, like ["pricing","adversarial"]. No prose.'
)


class ArchetypeTagger:
    """Haiku wrapper. Lazily instantiates the SDK so tests can avoid network."""

    def __init__(
        self,
        budget: LLMBudget,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.budget = budget
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY', '')
        self.model = model or os.getenv(
            'CAIRN_INTEL_BULK_MODEL', 'claude-haiku-4-5-20251001'
        )
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    # ── summarisation ───────────────────────────────────────────────────

    def summarise(self, raw_text: str, source_label: str = 'unknown') -> str:
        self.budget.consume_bulk(source=source_label)
        client = self._get_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=300,
            system=_SUMMARISE_SYSTEM,
            messages=[{'role': 'user', 'content': raw_text[:8000]}],
        )
        return _first_text(resp).strip()

    # ── tagging ─────────────────────────────────────────────────────────

    def tag(self, summary: str, source_label: str = 'unknown') -> list[str]:
        self.budget.consume_bulk(source=source_label)
        client = self._get_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=120,
            system=_TAG_SYSTEM,
            messages=[{'role': 'user', 'content': summary[:4000]}],
        )
        raw = _first_text(resp).strip()
        return _parse_tags(raw)


# ── Helpers ────────────────────────────────────────────────────────────


def _first_text(response: Any) -> str:
    """Pull the first text block out of an Anthropic response."""
    try:
        for block in response.content:
            if getattr(block, 'type', '') == 'text':
                return block.text
    except Exception:
        pass
    return ''


def _parse_tags(raw: str) -> list[str]:
    """Parse the tag LLM output into a validated tag list.

    Accepts ``["pricing","adversarial"]`` or ``pricing, adversarial``.
    Silently drops anything not in the canonical taxonomy.
    """
    tags: list[str] = []
    raw = raw.strip()
    if not raw:
        return tags
    # Try JSON first
    parsed: Any = None
    try:
        parsed = json.loads(raw)
    except Exception:
        # Fall back to comma-split
        parsed = [part.strip(' "\'[]') for part in raw.split(',')]
    if not isinstance(parsed, list):
        return tags
    valid = set(ARCHETYPES)
    for item in parsed:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().lower()
        if cleaned in valid and cleaned not in tags:
            tags.append(cleaned)
    return tags[:4]
