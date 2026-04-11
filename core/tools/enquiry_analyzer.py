"""
Chat tool — analyze_enquiry.

Takes a free-text new enquiry (an email, a phone note, a quote
request) and produces a structured strategy brief that synthesises
every retrieval layer Cairn has:

  1. search_crm                — live CRM state for this client
                                  (or similar clients if new)
  2. retrieve_similar_decisions — counterfactual memory
                                  (disputes + b2b_quotes + crm_lessons
                                   + crm_reflections + material_prices)
                                  + related wiki articles baked in
  3. search_wiki                — policy / SOP knowledge that may not
                                  have been surfaced through the
                                  related_wiki cross-link

Plus a fixed RATE_CARD block loaded from
``wiki/modules/nbne-rate-card.md`` — always in context so the
analyzer can quote current NBNE rates without having to discover
them through retrieval.

Output is a markdown strategy document with:

  - archetype classification
  - retrieved evidence (with citations to specific decision_ids and
    wiki file paths — no un-grounded claims)
  - game-theoretic framing (parties, objectives, BATNAs, moves)
  - recommended strategy + concrete next-step actions
  - risk flags
  - confidence rating

Output length is CALIBRATED to the job's estimated value:
  - Under £500:  terse brief (300-500 chars, 2-3 actions, suggested
                 copy for message-bearing signage, no tables/games)
  - £500-£5000:  mid brief (800-1200 chars, 3-5 actions, lightweight
                 archetype + precedent analysis)
  - £5000+:      full brief (2500-3500 chars, archetype, game theory,
                 tiered options, precedent chains, risks)

Precedents passed to the synthesis step are annotated with a
value-size match signal so Sonnet can down-weight precedents that
are much bigger or smaller than the current enquiry.

The tool is READ-ONLY and SAFE — it retrieves, reasons, and
recommends. It never writes anywhere. The user retains decision
authority; the tool's opening line explicitly says "recommendation,
not decision".
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from .registry import Tool, RiskLevel


log = logging.getLogger(__name__)


CRM_DEFAULT_BASE_URL = 'https://crm.nbnesigns.co.uk'
ANTHROPIC_SONNET_MODEL_ENV = 'CLAUDE_MODEL'
DEFAULT_SONNET_MODEL = 'claude-sonnet-4-6'

RATE_CARD_FILES = (
    # In-container path (production on Hetzner)
    '/app/wiki/modules/nbne-rate-card.md',
    # Dev-box path (D:/claw) — resolved relative to this file
    str(Path(__file__).parent.parent.parent / 'wiki' / 'modules' / 'nbne-rate-card.md'),
)
RATE_CARD_MAX_CHARS = 6000


# Archetypes that imply message-bearing signage — the prompt will
# mandate a SUGGESTED COPY section for enquiries matching these.
MESSAGE_BEARING_KEYWORDS = (
    'a-board', 'a board', 'pavement sign', 'sandwich board',
    'poster', 'banner', 'event sign', 'fascia', 'shopfront',
    'shop front', 'shop sign', 'window sign', 'menu board',
    'sandwich sign', 'flag', 'wayfinding',
)


_ANALYSIS_SYSTEM = (
    'You are a senior business strategist at NBNE, a Northumberland '
    'signage manufacturer. A new enquiry has arrived. Your job is to '
    'analyse it against NBNE\'s historical decision memory and '
    'produce a STRATEGIC BRIEF with concrete recommendations the '
    'operator can act on today.\n\n'
    'You will receive:\n'
    '  - The raw enquiry text\n'
    '  - RATE_CARD: NBNE\'s authoritative published rates\n'
    '  - CRM_CONTEXT: relevant live records (projects, clients, '
    'materials, lessons) from search_crm\n'
    '  - DECISION_CONTEXT: counterfactual memory matches from '
    'retrieve_similar_decisions (disputes, b2b_quotes, crm_lessons, '
    'crm_reflections, material_prices), each annotated with a '
    'VALUE_MATCH marker showing whether the precedent is the same '
    'order of magnitude as the current enquiry\n'
    '  - WIKI_CONTEXT: policy and process articles from search_wiki\n\n'
    'STEP 1 — Estimate job value\n'
    'Before producing the brief, estimate the ballpark value of this '
    'job in ONE sentence. Base your estimate on: (a) the scope '
    'described in the enquiry, (b) rates from the RATE_CARD, (c) '
    'size-matched precedents from DECISION_CONTEXT. Write the estimate '
    'as the very first line of your output, like:\n'
    '  _Estimated value: £50–£200 — small pavement sign replacement panels._\n\n'
    'STEP 2 — Scale brief length to value\n'
    'The length and depth of the rest of the brief depends on the '
    'estimated value:\n'
    '\n'
    '  **Under £500 (small job)**: return ONLY — \n'
    '    - SUGGESTED RESPONSE section with 3-5 line copy draft if\n'
    '      this is message-bearing signage (A-board, pavement sign,\n'
    '      poster, fascia with text, etc)\n'
    '    - 2-3 CONCRETE ACTIONS (numbered, citing specific rates or\n'
    '      precedents where relevant)\n'
    '    - BOTTOM LINE: one sentence\n'
    '    Target 400-600 chars of brief content. No archetype table,\n'
    '    no game theory section, no precedent chains. Be tight.\n'
    '\n'
    '  **£500-£5,000 (mid job)**: full-structure brief but concise:\n'
    '    - Archetype (one line, 1-3 tags)\n'
    '    - 3-5 CONCRETE ACTIONS with citations\n'
    '    - 2-3 RISK FLAGS\n'
    '    - Strategic posture (one sentence)\n'
    '    - SUGGESTED RESPONSE if message-bearing\n'
    '    Target 800-1500 chars.\n'
    '\n'
    '  **£5,000+ (large job)**: expansive brief:\n'
    '    - Full archetype classification\n'
    '    - Game-theoretic framing (parties, objectives, BATNAs, moves)\n'
    '    - Information asymmetry check\n'
    '    - Tiered quote recommendation\n'
    '    - 5 CONCRETE ACTIONS with citations\n'
    '    - Full RISK section\n'
    '    - Strategic posture paragraph\n'
    '    - SUGGESTED RESPONSE if message-bearing\n'
    '    Target 2500-3500 chars.\n'
    '\n'
    'STEP 3 — Suggested response copy for message-bearing signage\n'
    'If the enquiry is for an A-board, pavement sign, poster, banner, '
    'event sign, fascia/shopfront with text, wayfinding sign, or any '
    'other signage whose core purpose is to convey a specific message, '
    'you MUST include a SUGGESTED COPY section with 3-5 lines of '
    'concrete draft text. Use short lines, ALL CAPS for key phrases, '
    'bullet separators (•) for lists of features. Base the copy on '
    'what the client actually said they want to convey. This is a '
    'high-value move that moves the client toward a decision — never '
    'skip it for message-bearing jobs.\n\n'
    'STEP 4 — Grounding rules (apply to every brief regardless of size)\n'
    '1. GROUND EVERY CLAIM. When you state something about a past '
    'decision, cite the decision_id. When you state a policy, cite '
    'the wiki file_path. When you quote a rate, cite the RATE_CARD. '
    'If you cannot cite, say "reasoning from principles, no precedent '
    'found" explicitly.\n'
    '2. **NEVER invent a rate that is not in the RATE_CARD.** If the '
    'RATE_CARD marks a rate as TBC or is missing, the action should '
    'be "ask Toby for a firm quote on X" — do NOT guess a number.\n'
    '3. Prefer precedents marked VALUE_MATCH: same_order over those '
    'marked VALUE_MATCH: bigger_job or smaller_job. If you must cite '
    'an out-of-band precedent, note its relevance explicitly as '
    '"(weak precedent — larger/smaller job shape)".\n'
    '4. For archetype classification use the closed 8-tag taxonomy: '
    'adversarial, cooperative, time_pressured, information_asymmetric, '
    'repeated_game, one_shot, pricing, operational. Pick 1-4.\n'
    '5. Always include planning permission / advertisement consent '
    'flag if fascia, shopfront or conservation area is mentioned.\n\n'
    'STEP 5 — Framing\n'
    'The document is a RECOMMENDATION. Start with '
    '"**Recommendation, not decision.**" Close the brief with a '
    'pointed question that helps the operator decide (e.g. '
    '"What\'s your BATNA here?" for negotiations, "Ready to send?" '
    'for simple quote responses, "What does your gut say about the '
    'client\'s seriousness?" for ambiguous cases).\n\n'
    'Return a markdown document. No code fences. No preamble.'
)


def _load_rate_card() -> str:
    """Read the canonical rate card from disk.

    Tries the in-container path first (/app/wiki/modules/...) and
    falls back to the dev-box path resolved from this file. If
    neither works, returns a short stub so the analyzer still runs
    without the rate card block.
    """
    for path in RATE_CARD_FILES:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if len(content) > RATE_CARD_MAX_CHARS:
                content = content[:RATE_CARD_MAX_CHARS] + '\n\n...[truncated]'
            return content
        except FileNotFoundError:
            continue
        except Exception as exc:
            log.warning('analyze_enquiry: rate card load failed at %s: %s', path, exc)
            continue
    return (
        '# NBNE Rate Card (not found)\n\n'
        '**Labour and graphic design rate**: £40/hour ex VAT.\n\n'
        '_Rate card file not loaded — other rates are unknown. '
        'If you need to quote anything beyond the hourly rate, '
        'the analyzer should flag it as "ask Toby for a firm '
        'quote" rather than guessing._'
    )


def _estimate_enquiry_value(enquiry: str) -> tuple[float | None, float | None]:
    """Extract a very rough value hint from the enquiry text.

    Looks for any £ amount mentioned (budget statements, previous
    quotes, etc). Returns (low, high) estimate if found, else
    (None, None). This is a crude first pass — the synthesis step
    does a better job with full context, but this hint helps the
    retrieve_similar call size-match precedents.
    """
    if not enquiry:
        return None, None
    matches = re.findall(r'£\s?([\d,]+(?:\.\d+)?)', enquiry)
    if not matches:
        return None, None
    numbers: list[float] = []
    for m in matches:
        try:
            numbers.append(float(m.replace(',', '')))
        except ValueError:
            continue
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def _annotate_decision_context_with_value_match(
    decision_context: str,
    enquiry_value_low: float | None,
    enquiry_value_high: float | None,
) -> str:
    """Post-process the decision context to add VALUE_MATCH markers.

    The CRM reflection records carry crm_metadata.value in their
    raw_source_ref — when Sonnet sees the DECISION_CONTEXT block,
    we want each decision tagged with same_order / bigger_job /
    smaller_job so it can prefer size-matched precedents.

    Since we don't have direct DB access to the raw_source_ref at
    this layer (we have the already-formatted tool output string),
    we look for £ amounts in the formatted text and annotate based
    on proximity to the enquiry's estimated value. Best-effort and
    silently returns the original text if no annotations are needed.
    """
    if enquiry_value_low is None or enquiry_value_high is None:
        return decision_context
    midpoint = (enquiry_value_low + enquiry_value_high) / 2.0
    if midpoint <= 0:
        return decision_context

    # For each line mentioning a £ amount, classify it and append
    # a compact size-match tag.
    lines = decision_context.splitlines()
    annotated: list[str] = []
    for line in lines:
        amounts = re.findall(r'£\s?([\d,]+(?:\.\d+)?)', line)
        if not amounts:
            annotated.append(line)
            continue
        try:
            values = [float(a.replace(',', '')) for a in amounts]
        except ValueError:
            annotated.append(line)
            continue
        if not values:
            annotated.append(line)
            continue
        top = max(values)
        if top <= 0:
            annotated.append(line)
            continue
        ratio = top / midpoint
        if 0.5 <= ratio <= 2.0:
            tag = ' [VALUE_MATCH: same_order]'
        elif ratio > 2.0:
            tag = f' [VALUE_MATCH: bigger_job ({ratio:.1f}x)]'
        else:
            tag = f' [VALUE_MATCH: smaller_job ({ratio:.2f}x)]'
        annotated.append(line + tag)
    return '\n'.join(annotated)


def _is_message_bearing_signage(enquiry: str) -> bool:
    """Heuristic: does the enquiry mention message-bearing signage?"""
    lowered = enquiry.lower()
    return any(kw in lowered for kw in MESSAGE_BEARING_KEYWORDS)


# ── Retrieval wrappers ─────────────────────────────────────────────────


def _search_crm_safe(query: str, limit: int = 5) -> str:
    try:
        from .crm_tools import _search_crm
        return _search_crm(project_root='', query=query, limit=limit)
    except Exception as exc:
        return f'(search_crm unavailable: {exc})'


def _retrieve_similar_safe(query: str, limit: int = 6) -> str:
    try:
        from .intel_tools import _retrieve_similar_decisions
        return _retrieve_similar_decisions(
            project_root='', query=query, limit=limit,
        )
    except Exception as exc:
        return f'(retrieve_similar_decisions unavailable: {exc})'


def _search_wiki_safe(query: str, limit: int = 5) -> str:
    try:
        from .cairn_tools import _search_wiki
        return _search_wiki(project_root='', query=query, limit=limit)
    except Exception as exc:
        return f'(search_wiki unavailable: {exc})'


# ── Tool entry point ───────────────────────────────────────────────────


def _analyze_enquiry(
    project_root: str,
    enquiry: str,
    focus: str | None = None,
    **kwargs,
) -> str:
    if not enquiry or not enquiry.strip():
        return 'analyze_enquiry: enquiry text is required'

    enquiry = enquiry.strip()
    focus_suffix = f' — focus: {focus}' if focus and focus.strip() else ''

    anthropic_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not anthropic_key:
        return (
            'analyze_enquiry: ANTHROPIC_API_KEY is not set — cannot run '
            'the synthesis step. Retrieval is available individually '
            'via search_crm / retrieve_similar_decisions / search_wiki.'
        )

    sonnet_model = os.getenv(ANTHROPIC_SONNET_MODEL_ENV, DEFAULT_SONNET_MODEL)

    # Compose retrieval queries from the enquiry text.
    query_text = (enquiry + focus_suffix)[:500]

    crm_context = _search_crm_safe(query_text, limit=5)
    decision_context_raw = _retrieve_similar_safe(query_text, limit=6)
    wiki_context = _search_wiki_safe(query_text, limit=5)

    # Improvement D — annotate retrieved decisions with VALUE_MATCH
    # markers so Sonnet can prefer precedents in the same order of
    # magnitude as the current enquiry.
    enquiry_low, enquiry_high = _estimate_enquiry_value(enquiry)
    decision_context = _annotate_decision_context_with_value_match(
        decision_context_raw,
        enquiry_low,
        enquiry_high,
    )

    # Improvement A — always inject the rate card as fixed context.
    rate_card = _load_rate_card()

    # Improvement C — hint to the model that this is message-bearing
    # so it definitely produces a SUGGESTED COPY section. This is
    # belt-and-braces on top of the system prompt instruction.
    message_bearing_hint = ''
    if _is_message_bearing_signage(enquiry):
        message_bearing_hint = (
            '\n\nNOTE: This enquiry appears to be for message-bearing '
            'signage (A-board, pavement sign, poster, fascia, etc). '
            'The SUGGESTED COPY section is MANDATORY in the brief — '
            'include 3-5 lines of concrete draft text the operator '
            'could put in front of the client today.'
        )

    synthesis_input = (
        f'ENQUIRY:\n{enquiry}\n\n'
        f'---\n'
        f'RATE_CARD (authoritative NBNE rates — cite these, never invent numbers):\n'
        f'{rate_card}\n\n'
        f'---\n'
        f'CRM_CONTEXT (live records matching the enquiry):\n{crm_context}\n\n'
        f'---\n'
        f'DECISION_CONTEXT (past decisions + related wiki, from cairn_intel, '
        f'annotated with VALUE_MATCH markers):\n'
        f'{decision_context}\n\n'
        f'---\n'
        f'WIKI_CONTEXT (policy and process articles):\n{wiki_context}\n'
        f'{message_bearing_hint}\n\n'
        f'---\n'
        'Produce the strategic brief now. Start with the estimated '
        'value line, then scale the rest of the brief to that value.'
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model=sonnet_model,
            max_tokens=2500,
            system=_ANALYSIS_SYSTEM,
            messages=[{'role': 'user', 'content': synthesis_input}],
        )
    except Exception as exc:
        return (
            f'analyze_enquiry: synthesis step failed ({exc}). '
            f'Retrieval ran — you can see results via search_crm, '
            f'retrieve_similar_decisions, and search_wiki separately.'
        )

    brief = _first_text(resp).strip()
    if not brief:
        return (
            'analyze_enquiry: synthesis step returned empty output. '
            'Retrieval ran but Sonnet did not produce a brief.'
        )

    # Provenance footer
    footer = (
        '\n\n---\n'
        '_Provenance:_\n'
        f'- search_crm: {len(crm_context)} chars\n'
        f'- retrieve_similar_decisions: {len(decision_context)} chars '
        f'(value-annotated)\n'
        f'- search_wiki: {len(wiki_context)} chars\n'
        f'- rate_card: {len(rate_card)} chars '
        f'(from wiki/modules/nbne-rate-card.md)\n'
        f'- synthesis model: {sonnet_model}'
    )
    return brief + footer


def _first_text(resp: Any) -> str:
    try:
        for block in resp.content:
            if getattr(block, 'type', '') == 'text':
                return block.text
    except Exception:
        pass
    return ''


analyze_enquiry_tool = Tool(
    name='analyze_enquiry',
    description=(
        'Analyse a new enquiry against NBNE\'s historical decision '
        'memory and return a structured strategy brief with citations. '
        'Use this when the user asks "how should we handle this quote", '
        '"what should I say to this client", "is this a good '
        'opportunity", or pastes in a new enquiry / email / quote '
        'request and wants a recommendation. '
        'The tool runs search_crm + retrieve_similar_decisions + '
        'search_wiki internally to gather evidence, loads NBNE\'s '
        'rate card from wiki/modules/nbne-rate-card.md, then uses '
        'Claude Sonnet to synthesise a markdown brief. '
        'Output length is calibrated to the estimated job value — '
        'small jobs get a tight brief with suggested response copy; '
        'large jobs get archetype, game-theoretic framing, tiered '
        'quotes, and precedent analysis. Every claim grounded in a '
        'cited decision_id, wiki file_path, or RATE_CARD line; the '
        'analyzer never invents rates. '
        'Arguments: enquiry (required, free text — paste the full '
        'enquiry), focus (optional hint, e.g. "pricing" or "dispute"). '
        'Output is a RECOMMENDATION, not a decision — final '
        'authority stays with the user.'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_analyze_enquiry,
    required_permission='analyze_enquiry',
)
