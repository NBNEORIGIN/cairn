"""Draft a reply to an incoming client email using local Ollama.

Part of the Triage Phase A loop (2026-04-21). The drafter is invoked
after the classifier + project matcher — given the incoming email,
the top candidate project's history, and the tone config, produce a
short reply the user can accept, edit, or reject via the reply-back
block in the digest.

Discipline:

  * Local inference only — uses OLLAMA_BASE_URL (deek-gpu via
    Tailscale) with qwen2.5:7b-instruct as the default. Zero cloud
    cost per draft.
  * Graceful degradation — any failure returns an empty draft with
    an explanatory note. Never raises. The digest still sends.
  * Short. Target 80 words, hard max 180. Low-confidence drafts go
    to 40 words — don't write confidently wrong at length.
  * The tone config in config/email_triage/response_tone.yaml is
    loaded on every call so PR'd tone changes apply without a redeploy.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TONE_PATH = Path(
    os.getenv('DEEK_RESPONSE_TONE',
              str(_REPO_ROOT / 'config' / 'email_triage' / 'response_tone.yaml'))
)

OLLAMA_TIMEOUT = 45.0
DEFAULT_MODEL = 'qwen2.5:7b-instruct'


@dataclass
class DraftResult:
    text: str                 # the draft reply, empty on any failure
    model: str
    confidence_note: str      # e.g. '[uncertain]' or ''
    error: str                # populated on failure; empty on success


def _load_tone() -> dict:
    """Load the tone YAML. Returns {} with a warning on any failure."""
    if not _TONE_PATH.exists():
        logger.warning('[response_drafter] tone file missing: %s', _TONE_PATH)
        return {}
    try:
        import yaml
        return yaml.safe_load(_TONE_PATH.read_text(encoding='utf-8')) or {}
    except Exception as exc:
        logger.warning('[response_drafter] tone load failed: %s', exc)
        return {}


def _build_prompt(
    email: dict,
    candidate: dict | None,
    project_history: str,
    tone: dict,
    low_confidence: bool,
) -> str:
    """Assemble the Ollama prompt. Deterministic given inputs — no
    randomness here."""
    voice = (tone.get('voice') or {}).get('description', '').strip()
    rules_list = tone.get('rules') or []
    length_cfg = tone.get('length') or {}
    target_words = length_cfg.get(
        'low_confidence_target_words' if low_confidence else 'target_words',
        80,
    )
    max_words = length_cfg.get('max_words', 180)

    rules_block = '\n'.join(f'  - {r}' for r in rules_list) if rules_list else '  (no explicit rules)'

    # Candidate block — what we believe the email is about. Includes
    # match score so the drafter can hedge when uncertain.
    if candidate and candidate.get('project_id'):
        cand_block = (
            f"Matched project (confidence {candidate.get('match_score', 0):.3f}):\n"
            f"  id:   {candidate.get('project_id')}\n"
            f"  name: {candidate.get('project_name') or '(unnamed)'}\n"
            f"  last activity: {candidate.get('last_activity_at') or '(unknown)'}\n"
        )
    else:
        cand_block = "Matched project: none found above the confidence bar.\n"

    history_block = project_history.strip() if project_history else '(no prior history retrieved)'

    body = (email.get('body_text') or email.get('body') or '').strip()
    # Strip long quoted tails — the drafter only needs the fresh part.
    body_lines: list[str] = []
    for line in body.splitlines():
        if line.lstrip().startswith('>'):
            break
        if line.lstrip().startswith('On ') and 'wrote:' in line:
            break
        body_lines.append(line)
    body_clean = '\n'.join(body_lines).strip()[:3000]

    prompt = f"""You are drafting a reply email on behalf of Toby at NBNE (North By North East Print & Sign Ltd, Alnwick). This is NOT a chat reply — it is a fully-formed email reply ready for Toby to paste into his email client with minimal editing.

## Voice
{voice}

## Rules
{rules_block}

## Length
Target around {target_words} words. Hard maximum {max_words} words. Shorter is better than padded. Do NOT exceed the hard max.

## Incoming email
From:    {email.get('sender') or '(unknown)'}
Subject: {email.get('subject') or '(no subject)'}

{body_clean or '(empty body)'}

## Project context
{cand_block}

## Prior project history (for grounding — do NOT invent details beyond this)
{history_block}

## Output format
Respond with JSON only, no prose wrapping:

{{
  "draft": "full reply text including greeting and sign-off",
  "confidence": "high | medium | low",
  "needs_followup": true | false,
  "notes": "optional single sentence to Toby about assumptions you made"
}}

If there is not enough context to draft a reply that wouldn't be confidently wrong, return:

{{
  "draft": "",
  "confidence": "none",
  "needs_followup": true,
  "notes": "why you couldn't draft"
}}
"""
    return prompt


def _parse_response(raw: str) -> tuple[str, str, str]:
    """Extract (draft, confidence, notes) from the Ollama response.

    Tolerates surrounding prose by finding the first { ... }. Returns
    ('', 'none', error_msg) on any parse failure.
    """
    if not raw:
        return '', 'none', 'empty response'
    start = raw.find('{')
    end = raw.rfind('}')
    if start < 0 or end < start:
        return '', 'none', 'no JSON object in response'
    try:
        obj = json.loads(raw[start:end + 1])
    except Exception as exc:
        return '', 'none', f'JSON parse failed: {exc}'
    draft = str(obj.get('draft') or '').strip()
    confidence = str(obj.get('confidence') or 'none').lower()
    notes = str(obj.get('notes') or '').strip()
    return draft, confidence, notes


def draft_reply(
    email: dict,
    candidate: dict | None = None,
    project_history: str = '',
    ollama_base: str | None = None,
    model: str | None = None,
    low_confidence: bool = False,
) -> DraftResult:
    """Produce a draft reply. Never raises.

    Args:
        email: keys sender, subject, body_text (or body).
        candidate: top match candidate from project_matcher, or None
            when no match scored above threshold.
        project_history: pre-formatted string of project history
            (quotes, prior emails, last activity) — the drafter uses
            it for grounding. Empty string is fine.
        ollama_base: override for OLLAMA_BASE_URL.
        model: override for the model name.
        low_confidence: if True, target a shorter draft.

    Returns a DraftResult. On any failure, DraftResult.text is empty
    and DraftResult.error explains why.
    """
    base = (ollama_base or os.getenv('OLLAMA_BASE_URL')
            or 'http://localhost:11434').rstrip('/')
    model = model or os.getenv(
        'DEEK_RESPONSE_DRAFTER_MODEL',
        os.getenv('OLLAMA_VOICE_MODEL', DEFAULT_MODEL),
    )

    tone = _load_tone()
    prompt = _build_prompt(email, candidate, project_history, tone, low_confidence)

    try:
        with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
            r = client.post(
                f'{base}/api/chat',
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'stream': False,
                    'options': {
                        'num_predict': 600,
                        'temperature': 0.3,
                    },
                },
            )
        if r.status_code != 200:
            return DraftResult(
                text='', model=model,
                confidence_note='',
                error=f'ollama HTTP {r.status_code}: {r.text[:200]}',
            )
        raw = (r.json().get('message') or {}).get('content', '').strip()
    except Exception as exc:
        return DraftResult(
            text='', model=model, confidence_note='',
            error=f'{type(exc).__name__}: {exc}',
        )

    draft, confidence, notes = _parse_response(raw)
    if not draft:
        return DraftResult(
            text='', model=model, confidence_note='',
            error=f'parse failed: {notes}',
        )

    # Append a terse confidence flag the digest can surface alongside
    # the draft — keeps the digest scan-friendly.
    conf_note = ''
    if confidence in ('low', 'none'):
        conf_note = '[uncertain — drafted with limited context]'
    elif notes:
        conf_note = f'[note: {notes[:200]}]'

    return DraftResult(
        text=draft, model=model, confidence_note=conf_note, error='',
    )


__all__ = ['DraftResult', 'draft_reply']
