"""
core.triage.edit_review — pre-save AI review of Toby's edits to a
Deek-drafted email reply. Phase 6 of inbox learning loop.

Stance: Toby is the author of record. The AI plays sub-editor — flags
typos, factual inconsistencies, and tone drift, but never overrides.
Findings come back as a structured list the inbox UI renders inline,
each one with a one-click "apply suggested rewrite" if the AI proposed
one.

Cost: Haiku, not Sonnet. Reviews are short; this is a per-keystroke-
style ask (well, per-button-press), so optimise for latency + cost.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

REVIEW_MODEL = os.getenv('DEEK_EDIT_REVIEW_MODEL', 'claude-haiku-4-5-20251001')

SYSTEM_PROMPT = """You are a careful sub-editor reviewing a UK signage-business owner's edit to an AI-drafted email reply. The owner (Toby, at North By North East Print & Sign Ltd) edits these drafts before pasting into his email client and sending manually. Your job is to flag issues he'd want to catch.

You see three things:
  1. The incoming customer email (for context — what's being replied to)
  2. The AI's original draft (what Deek produced)
  3. Toby's edited version (what he'd send if you didn't catch anything)

Review Toby's EDITED version against the email context. Flag:
  - typos and clear spelling/grammar errors
  - factual concerns — numbers, dates, product names, names of people, technical specs, financial figures that don't match what's in the incoming email or that contradict themselves
  - tone notes — only call out tone if it's noticeably off-brand (overly formal where casual fits, or vice versa). Don't quibble for the sake of it.
  - missing follow-through — questions in the incoming email that the reply doesn't address

DON'T flag:
  - things that are merely "differently phrased" from the original AI draft (Toby's edit is the source of truth)
  - matters of taste
  - region-spelling: he's UK, "colour" and "organise" are correct

Output STRICTLY this JSON shape (no prose, no markdown fences):

{
  "verdict": "ship | minor_issues | needs_attention",
  "summary": "one short sentence — what's the headline?",
  "findings": [
    {
      "kind": "typo | factual | tone | follow_through",
      "severity": "low | medium | high",
      "issue": "what's wrong, one short sentence",
      "where": "short quote from Toby's text showing the problem",
      "suggestion": "the fix as Toby could paste it (optional — null if no concrete rewrite)"
    },
    ...
  ]
}

If everything reads clean, return verdict='ship', summary='Reads clean.', findings=[].
Aim for 0-5 findings; more than 5 means you're nitpicking — tighten the bar.
"""


def review_edit(
    *,
    email_body: str,
    original_draft: str,
    edited_draft: str,
    sender: str = '',
    subject: str = '',
) -> dict:
    """Call Claude Haiku for a structured review. Returns the parsed
    dict (or a small error envelope on failure)."""
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return {
            'verdict': 'ship', 'summary': 'AI review unavailable (no API key).',
            'findings': [], 'error': 'no_api_key',
        }

    try:
        import anthropic  # type: ignore
    except ImportError:
        return {
            'verdict': 'ship', 'summary': 'AI review unavailable (anthropic SDK missing).',
            'findings': [], 'error': 'no_sdk',
        }

    user_prompt = (
        f"## Incoming email\n"
        f"From: {sender or '(unknown)'}\n"
        f"Subject: {subject or '(no subject)'}\n\n"
        f"{(email_body or '').strip()[:6000]}\n\n"
        f"## Deek's original draft (for reference — DON'T review this)\n"
        f"{(original_draft or '').strip()[:4000]}\n\n"
        f"## Toby's edited version (review THIS)\n"
        f"{(edited_draft or '').strip()[:4000]}\n"
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        completion = client.messages.create(
            model=REVIEW_MODEL,
            max_tokens=2000,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        raw = (completion.content[0].text or '') if completion.content else ''
    except Exception as exc:
        logger.warning('edit_review: Claude call failed: %s', exc)
        return {
            'verdict': 'ship', 'summary': 'AI review failed.',
            'findings': [], 'error': str(exc)[:200],
        }

    parsed = _extract_json(raw)
    if not parsed:
        return {
            'verdict': 'ship', 'summary': 'AI review returned unparseable output.',
            'findings': [], 'error': 'unparseable',
            'raw_preview': raw[:500],
        }

    # Light sanity-cleanup.
    parsed.setdefault('verdict', 'ship')
    parsed.setdefault('summary', '')
    parsed.setdefault('findings', [])
    if not isinstance(parsed['findings'], list):
        parsed['findings'] = []
    return parsed


_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```')


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    m = _JSON_FENCE.search(text)
    candidate = m.group(1) if m else text
    start = candidate.find('{')
    end = candidate.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(candidate[start:end + 1])
    except Exception:
        return None
