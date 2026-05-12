"""Triage digest reply parser + apply — Phase B.

When Toby replies to a triage digest, the inbox poll indexes the
reply into `claw_code_chunks` (chunk_type='email'). This module
recognises those replies by subject, parses the 4-question answer
block, and applies the actions back to:

  * `cairn_intel.email_triage` — update confirmed project, stash
    approved/edited draft, record project folder path, mark review
  * CRM via `POST /api/cairn/memory` — add a note on the confirmed
    project with the approved reply
  * `claw_code_chunks` — write a new memory chunk with
    toby_flag=true for free-text notes and edit corrections

Categories:

    match_confirm
      YES              → keep candidate 1 as the confirmed project
      NO               → demote (clear confirmed project; log for
                           Phase C/D to surface alternatives later)
      "1"|"2"|"3"      → swap confirmed project to that candidate
      text             → free-text → open issue, logged; don't guess

    reply_approval
      USE              → treat draft_reply as the final approved text
      EDIT: <text>     → override draft with the edited text
      REJECT           → record that the draft was not usable; no
                           CRM note is posted (we don't want to paste
                           a rejected draft into the project history)
      text (no verb)   → treat as an EDIT: … with the whole text

    project_folder
      path string      → store in project_folder_path + CRM note
      empty            → no-op

    notes
      text             → write to claw_code_chunks with toby_flag=true,
                           link via provenance to the triage row

Idempotency via SHA over (raw_body + triage_id). Re-running against
the same inbox state is a no-op. Parse failures are logged and
captured in review_notes; the row still gets marked reviewed so
future runs don't retry the same bad reply forever.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Subject pattern on the OUTGOING digest is
#   [Deek] {classification} — {original_subject}
# A reply prefixes with Re: / RE: / FW: etc. We're deliberately loose
# on the separator (em-dash vs hyphen) because email clients re-encode.
_TRIAGE_REPLY_SUBJECT_RE = re.compile(
    r're:\s*\[deek\]\s+(existing_project_reply|new_enquiry)',
    re.IGNORECASE,
)

# Block delimiter — identical to the Memory Brief's.
_BLOCK_DELIM_RE = re.compile(
    r'^---\s*Q(\d+)\s*\(([a-z_]+)\)\s*---\s*$',
    re.MULTILINE,
)

_AFFIRMATIVE = frozenset({
    'yes', 'y', 'use', 'confirmed', 'correct', 'ok',
})
_NEGATIVE = frozenset({
    'no', 'n', 'reject', 'rejected', 'wrong', 'incorrect',
})
_CANDIDATE_NUMBER_RE = re.compile(r'^\s*([1-3])\s*$')
_EDIT_PREFIX_RE = re.compile(r'^\s*edit\s*:\s*', re.IGNORECASE)
# `PROJECT: <name>` override on Q1 — Toby types this when none of the
# 3 candidates fit. The name (or part of it, or the client name)
# resolves via CRM search in apply_reply. Added 2026-05-07.
_PROJECT_OVERRIDE_RE = re.compile(r'^\s*project\s*:\s*(.+?)\s*$', re.IGNORECASE)

# Q0 (email_classification) verdicts — Toby tells Deek what kind of
# email this is so the system can learn (spam blocklist, personal
# filter, new-enquiry training signal). EXISTING is the implicit
# default if Q0 is blank — preserves the legacy single-question flow.
# Added 2026-05-08.
_Q0_TOKENS = {
    'spam':         'spam',
    'junk':         'spam',
    'new':          'new_enquiry',
    'new_enquiry':  'new_enquiry',
    'newenquiry':   'new_enquiry',
    'enquiry':      'new_enquiry',
    'existing':     'existing',
    'personal':     'personal',
    'ignore':       'ignore',
    'skip':         'ignore',
}


# ── Data types ───────────────────────────────────────────────────────

@dataclass
class ParsedAnswer:
    q_number: int
    category: str
    raw_text: str
    verdict: str                  # affirm | deny | select_candidate | select_project | edit | text | empty
    selected_candidate_index: int | None = None   # 1-based when verdict='select_candidate'
    edited_text: str = ''         # populated when verdict='edit'
    free_text: str = ''           # populated when verdict='text', 'edit', or 'select_project'
    # When verdict='select_project': the typed project name/hint that
    # apply_reply will resolve against CRM. Stored on free_text.


@dataclass
class ParsedReply:
    triage_id: int | None
    user_email: str
    answers: list[ParsedAnswer] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)


# ── Subject handling ─────────────────────────────────────────────────

def is_triage_reply(subject: str) -> bool:
    """True if the subject matches our outgoing digest pattern."""
    if not subject:
        return False
    return bool(_TRIAGE_REPLY_SUBJECT_RE.search(subject))


def strip_reply_prefix(subject: str) -> str:
    """Drop leading 'Re: ' / 'FW: ' etc. to recover the original digest
    subject for matching. Lightweight — handles the common cases.
    """
    s = (subject or '').strip()
    for _ in range(3):
        lower = s.lower()
        if lower.startswith('re:') or lower.startswith('fw:'):
            s = s[3:].strip()
        elif lower.startswith('fwd:'):
            s = s[4:].strip()
        else:
            break
    return s


def match_triage_row_by_subject(
    conn, original_subject: str,
) -> int | None:
    """Find the triage row whose digest had this subject.

    Our outgoing subject is `[Deek] {classification} — {original_subject}`.
    We search backwards over the last 14 days (a user might reply to
    an older digest), matching by email_subject content. If multiple
    rows match, the most recent wins.
    """
    # Extract the original_subject slice after the em-dash
    # e.g. "[Deek] existing_project_reply — Re: Window displays"
    sep_idx = original_subject.find('—')
    if sep_idx < 0:
        sep_idx = original_subject.find(' - ')
    if sep_idx < 0:
        # No separator — fall back to searching the whole string
        needle = original_subject
    else:
        needle = original_subject[sep_idx + 1:].strip()
    if not needle:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM cairn_intel.email_triage
                WHERE email_subject = %s
                  AND classification = 'existing_project_reply'
                  AND processed_at > NOW() - INTERVAL '14 days'
                ORDER BY processed_at DESC
                LIMIT 1""",
            (needle,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


# ── Body parsing ─────────────────────────────────────────────────────

def strip_quoted(text: str) -> str:
    """Mirror of core.brief.replies.strip_quoted — drop quoted email
    tails so the original digest content doesn't pollute the parse.

    Requires '> ' (space) or '>>' for reply quoting. A bare '>' is
    mbox From-munging, not a quote — see core.brief.replies for the
    full note.

    If our structured ``--- Q<n> (category) ---`` delimiters are
    anywhere in the body, skip heuristic stripping entirely — the
    delimiters are ground truth (handles top-post clients that
    leave inline answers under an "On <date> wrote:" header).
    """
    if _BLOCK_DELIM_RE.search(text or ''):
        return (text or '').strip()
    lines: list[str] = []
    for line in (text or '').splitlines():
        stripped = line.lstrip()
        if stripped.startswith('> ') or stripped.startswith('>>'):
            break
        if stripped.startswith('--- Original Message ---'):
            break
        if re.match(r'^On .+wrote:\s*$', stripped):
            break
        lines.append(line)
    return '\n'.join(lines).strip()


def _classify_email_classification(text: str) -> ParsedAnswer:
    """Q0 verdict — top-level "what kind of email is this?".

    Verdicts:
      spam          → add sender DOMAIN to learned ignore list
      personal      → add sender EMAIL (exact) to learned ignore list
      new_enquiry   → write a training-signal memory chunk with the
                      email body so retrieval surfaces it next time
      existing      → fall through to Q1's project-pick (the default)
      ignore        → mark reviewed, no learning signal
      empty         → no Q0 answered; treat as 'existing' downstream

    Accepted input shapes (case-insensitive):
      'SPAM', 'JUNK', 'spam'
      'NEW_ENQUIRY', 'NEW', 'NEW ENQUIRY', 'NEW-ENQUIRY', 'ENQUIRY'
      'EXISTING'
      'PERSONAL'
      'IGNORE', 'SKIP'
    """
    cleaned = (text or '').strip()
    if not cleaned:
        return ParsedAnswer(
            q_number=0, category='email_classification',
            raw_text=text, verdict='empty',
        )
    first = cleaned.splitlines()[0].strip()
    # Normalise: collapse spaces/hyphens/underscores to one form for lookup
    normalised = re.sub(r'[\s\-_]+', '_', first.lower())
    if normalised in _Q0_TOKENS:
        verdict = _Q0_TOKENS[normalised]
    else:
        # Single-word lookup if the user typed extra context after the
        # keyword (e.g. "SPAM — cold sales pitch from Acme Marketing")
        first_word = re.split(r'[\s\-_:,]+', normalised, maxsplit=1)[0]
        verdict = _Q0_TOKENS.get(first_word, 'text')
    free_text = cleaned if verdict == 'text' else ''
    return ParsedAnswer(
        q_number=0, category='email_classification',
        raw_text=text, verdict=verdict, free_text=free_text,
    )


def _classify_match_confirm(text: str) -> ParsedAnswer:
    cleaned = text.strip()
    if not cleaned:
        return ParsedAnswer(q_number=1, category='match_confirm',
                            raw_text=text, verdict='empty')
    first = cleaned.splitlines()[0].strip()
    # `PROJECT: <name>` override beats everything else — Toby is
    # explicitly correcting Deek's match. Resolved against CRM in
    # apply_reply().
    m = _PROJECT_OVERRIDE_RE.match(first)
    if m:
        return ParsedAnswer(
            q_number=1, category='match_confirm', raw_text=text,
            verdict='select_project',
            free_text=m.group(1).strip(),
        )
    # Candidate number wins over YES/NO
    m = _CANDIDATE_NUMBER_RE.match(first)
    if m:
        return ParsedAnswer(
            q_number=1, category='match_confirm', raw_text=text,
            verdict='select_candidate',
            selected_candidate_index=int(m.group(1)),
        )
    first_tokens = re.split(r'[\s/,]+', first.lower())
    first_tokens = [t for t in first_tokens if t]
    if first_tokens and first_tokens[0] in _AFFIRMATIVE:
        return ParsedAnswer(q_number=1, category='match_confirm',
                            raw_text=text, verdict='affirm')
    if first_tokens and first_tokens[0] in _NEGATIVE:
        return ParsedAnswer(q_number=1, category='match_confirm',
                            raw_text=text, verdict='deny')
    return ParsedAnswer(q_number=1, category='match_confirm',
                        raw_text=text, verdict='text', free_text=cleaned)


def _classify_reply_approval(text: str) -> ParsedAnswer:
    cleaned = text.strip()
    if not cleaned:
        return ParsedAnswer(q_number=2, category='reply_approval',
                            raw_text=text, verdict='empty')
    # "EDIT: <text>" — support both EDIT on its own line with text
    # below AND inline "EDIT: whole edited reply".
    if _EDIT_PREFIX_RE.match(cleaned):
        edited = _EDIT_PREFIX_RE.sub('', cleaned, count=1).strip()
        return ParsedAnswer(
            q_number=2, category='reply_approval', raw_text=text,
            verdict='edit', edited_text=edited,
        )
    first = cleaned.splitlines()[0].strip().lower()
    if first in _AFFIRMATIVE or first == 'use':
        return ParsedAnswer(q_number=2, category='reply_approval',
                            raw_text=text, verdict='affirm')
    if first in _NEGATIVE:
        return ParsedAnswer(q_number=2, category='reply_approval',
                            raw_text=text, verdict='deny')
    # Multi-line reply without "USE" / "EDIT:" prefix — treat whole
    # block as the edited reply.
    return ParsedAnswer(
        q_number=2, category='reply_approval', raw_text=text,
        verdict='edit', edited_text=cleaned,
    )


def _classify_simple_text(q: int, category: str, text: str) -> ParsedAnswer:
    cleaned = (text or '').strip()
    if not cleaned:
        return ParsedAnswer(q_number=q, category=category,
                            raw_text=text, verdict='empty')
    return ParsedAnswer(q_number=q, category=category,
                        raw_text=text, verdict='text', free_text=cleaned)


_SKIP_WORDS = frozenset({'skip', 'none', 'n/a', 'na', '-', 'pass'})


def _classify_similar_job_useful(text: str) -> ParsedAnswer:
    """Q5 — which similar past job was useful for this quote?

    Accepted shapes:
      * '1' / '2' / '3'        → select_candidate
      * 'SKIP' / 'NONE' / '-'  → empty (no-op, no learning signal)
      * free text              → text (captured verbatim as a note)
    """
    cleaned = (text or '').strip()
    if not cleaned:
        return ParsedAnswer(q_number=5, category='similar_job_useful',
                            raw_text=text, verdict='empty')
    first = cleaned.splitlines()[0].strip()
    if first.lower() in _SKIP_WORDS:
        return ParsedAnswer(q_number=5, category='similar_job_useful',
                            raw_text=text, verdict='empty')
    m = _CANDIDATE_NUMBER_RE.match(first)
    if m:
        return ParsedAnswer(
            q_number=5, category='similar_job_useful', raw_text=text,
            verdict='select_candidate',
            selected_candidate_index=int(m.group(1)),
        )
    return ParsedAnswer(q_number=5, category='similar_job_useful',
                        raw_text=text, verdict='text', free_text=cleaned)


def _strip_format_hint(text: str) -> str:
    """Drop the '(Expected reply format: ...)' hint lines if the user
    left them intact."""
    return '\n'.join(
        line for line in text.splitlines()
        if not line.lstrip().startswith('(Expected reply format:')
    ).strip()


def parse_reply_body(
    body: str,
    user_email: str,
    triage_id: int | None,
    *,
    triage_context: dict | None = None,
) -> ParsedReply:
    """Split a triage-reply body into answer blocks.

    Same delimiter contract as the Memory Brief. Each block is
    classified according to the category (four fixed categories for
    triage).

    When no delimiters are found and ``triage_context`` is provided
    (with keys: match_candidates, draft_reply), the body is routed
    through the conversational normaliser so Toby can reply in
    plain prose. Shadow-mode gated.
    """
    reply = ParsedReply(triage_id=triage_id, user_email=user_email)
    stripped = strip_quoted(body or '')
    if not stripped:
        reply.parse_notes.append('body empty after quote stripping')
        return reply

    matches = list(_BLOCK_DELIM_RE.finditer(stripped))
    if not matches:
        # Try the conversational normaliser when we have the triage
        # context to build a proper question list.
        if triage_context:
            conv_answers = _normalise_triage_conversational(
                stripped, triage_context,
            )
            if conv_answers:
                reply.parse_notes.append(
                    f'conversational-fallback: normalised {len(conv_answers)} answers'
                )
                reply.answers = conv_answers
                return reply
        reply.parse_notes.append('no Q<n> delimiters found; treating whole body as notes')
        reply.answers.append(_classify_simple_text(4, 'notes', stripped))
        return reply

    for i, m in enumerate(matches):
        q_num = int(m.group(1))
        category = m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
        block_text = _strip_format_hint(stripped[start:end].strip())

        if category == 'email_classification':
            reply.answers.append(_classify_email_classification(block_text))
        elif category == 'match_confirm':
            reply.answers.append(_classify_match_confirm(block_text))
        elif category == 'reply_approval':
            reply.answers.append(_classify_reply_approval(block_text))
        elif category in ('project_folder', 'notes'):
            reply.answers.append(
                _classify_simple_text(q_num, category, block_text),
            )
        elif category == 'similar_job_useful':
            reply.answers.append(
                _classify_similar_job_useful(block_text),
            )
        else:
            # Unknown category — preserve for diagnostics
            reply.parse_notes.append(f'unknown category: {category}')
            reply.answers.append(
                _classify_simple_text(q_num, category, block_text),
            )
    return reply


# ── DB + CRM operations ──────────────────────────────────────────────

def _normalise_triage_conversational(
    body: str, triage_context: dict,
) -> list[ParsedAnswer]:
    """Route a free-form triage reply through the local-LLM normaliser.

    ``triage_context`` comes from ``load_triage_row`` and should have
    ``match_candidates`` and ``draft_reply``. Returns a list of
    ``ParsedAnswer`` (possibly empty). Never raises.
    """
    try:
        from core.brief.conversational import (
            ConversationalQuestion, normalise_conversational_reply,
        )
    except Exception:
        return []

    candidates = triage_context.get('match_candidates') or []
    cand_lines = []
    for i, c in enumerate(candidates[:3], 1):
        name = (c or {}).get('project_name') or '(unnamed)'
        pid = (c or {}).get('project_id') or ''
        cand_lines.append(f'{i}. {name} (id={pid})')
    cand_block = '\n'.join(cand_lines) if cand_lines else '(none)'

    draft = (triage_context.get('draft_reply') or '').strip()
    draft_preview = (draft[:400] + '…') if len(draft) > 400 else draft

    questions = [
        ConversationalQuestion(
            q_number=1, category='match_confirm',
            prompt=(
                'Is the #1 candidate the correct project? '
                'If a different candidate is correct, name which. '
                'If none is correct, say so.'
            ),
            extra=f'Candidates:\n{cand_block}',
        ),
        ConversationalQuestion(
            q_number=2, category='reply_approval',
            prompt=(
                'Send the drafted reply as-is, reject it, or rewrite it?'
            ),
            extra=f'Draft reply:\n{draft_preview}' if draft else '(no draft)',
        ),
        ConversationalQuestion(
            q_number=3, category='project_folder',
            prompt=(
                'If the user mentioned where this project lives on '
                'disk, capture that path. Otherwise empty.'
            ),
        ),
        ConversationalQuestion(
            q_number=4, category='notes',
            prompt=(
                'Any other notes the user wants remembered about '
                'this project or client?'
            ),
        ),
    ]
    try:
        normalised = normalise_conversational_reply(
            body, questions, kind='triage',
        )
    except Exception:
        return []
    if not normalised:
        return []

    out: list[ParsedAnswer] = []
    for n in normalised:
        if n.verdict == 'empty':
            out.append(ParsedAnswer(
                q_number=n.q_number, category=n.category,
                raw_text=body, verdict='empty',
            ))
            continue
        if n.category == 'match_confirm':
            if n.verdict == 'select_candidate':
                out.append(ParsedAnswer(
                    q_number=1, category='match_confirm',
                    raw_text=body, verdict='select_candidate',
                    selected_candidate_index=n.selected_candidate_index,
                ))
            elif n.verdict == 'affirm':
                out.append(ParsedAnswer(
                    q_number=1, category='match_confirm',
                    raw_text=body, verdict='affirm',
                ))
            elif n.verdict == 'deny':
                out.append(ParsedAnswer(
                    q_number=1, category='match_confirm',
                    raw_text=body, verdict='deny',
                ))
            else:  # 'text' / 'correct'
                out.append(ParsedAnswer(
                    q_number=1, category='match_confirm',
                    raw_text=body, verdict='text',
                    free_text=n.correction_text or n.free_text,
                ))
        elif n.category == 'reply_approval':
            if n.verdict == 'edit':
                out.append(ParsedAnswer(
                    q_number=2, category='reply_approval',
                    raw_text=body, verdict='edit',
                    edited_text=n.edited_text or n.correction_text,
                ))
            elif n.verdict == 'affirm':
                out.append(ParsedAnswer(
                    q_number=2, category='reply_approval',
                    raw_text=body, verdict='affirm',
                ))
            elif n.verdict == 'deny':
                out.append(ParsedAnswer(
                    q_number=2, category='reply_approval',
                    raw_text=body, verdict='deny',
                ))
            else:
                out.append(ParsedAnswer(
                    q_number=2, category='reply_approval',
                    raw_text=body, verdict='edit',
                    edited_text=n.correction_text or n.free_text,
                ))
        elif n.category in ('project_folder', 'notes'):
            text = n.free_text or n.correction_text
            if text:
                out.append(ParsedAnswer(
                    q_number=n.q_number, category=n.category,
                    raw_text=body, verdict='text',
                    free_text=text,
                ))
            else:
                out.append(ParsedAnswer(
                    q_number=n.q_number, category=n.category,
                    raw_text=body, verdict='empty',
                ))
    return out


def _connect():
    import psycopg2
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        raise RuntimeError('DATABASE_URL not set')
    return psycopg2.connect(db_url, connect_timeout=5)


def _persist_thread_association(
    conn, triage_id: int | None, project_id: str | None,
    user_email: str | None,
    *, source: str, action_dict: dict,
) -> None:
    """On YES / select_candidate: write the thread→project binding
    so subsequent messages on the same thread auto-attach.

    Failures are annotated on the action_dict for audit but never
    raise — the primary apply_reply flow must remain resilient.
    """
    if not (triage_id and project_id):
        return
    try:
        from .thread_association import (
            record_association, thread_id_for_triage,
            CONFIDENCE_CONFIRMED,
        )
        tid = thread_id_for_triage(conn, int(triage_id))
        if not tid:
            action_dict['thread_assoc'] = 'no thread_id resolvable'
            return
        row_id = record_association(
            conn,
            thread_id=tid,
            project_id=project_id,
            source=source,
            confidence=CONFIDENCE_CONFIRMED,
            associated_by=user_email,
        )
        action_dict['thread_assoc'] = (
            f'recorded thread_assoc id={row_id}' if row_id
            else 'thread_assoc write failed'
        )
    except Exception as exc:
        action_dict['thread_assoc'] = f'error: {type(exc).__name__}'


def _body_hash(raw_body: str, triage_id: int) -> str:
    h = hashlib.sha256()
    h.update(str(triage_id).encode('utf-8'))
    h.update(b'\0')
    h.update((raw_body or '').encode('utf-8', errors='replace'))
    return h.hexdigest()


def already_applied(conn, triage_id: int, raw_body: str) -> bool:
    """True iff a review with this exact body has already been applied.

    Per-row state lives in cairn_intel.email_triage.reviewed_at /
    review_notes. We encode the body hash into review_notes (prefix
    'sha256:<digest>') so a fresh reply to an already-reviewed row
    doesn't double-apply.
    """
    digest = _body_hash(raw_body, triage_id)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT review_notes FROM cairn_intel.email_triage
                WHERE id = %s""",
            (triage_id,),
        )
        row = cur.fetchone()
    if not row or not row[0]:
        return False
    return digest in str(row[0])


def load_triage_row(conn, triage_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, email_subject, email_sender, project_id,
                      match_candidates, draft_reply, draft_model
                 FROM cairn_intel.email_triage
                WHERE id = %s""",
            (triage_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    candidates = row[4]
    if isinstance(candidates, str):
        try:
            candidates = json.loads(candidates)
        except Exception:
            candidates = None
    return {
        'id': int(row[0]),
        'email_subject': row[1],
        'email_sender': row[2],
        'project_id': row[3],
        'match_candidates': candidates,
        'draft_reply': row[5],
        'draft_model': row[6],
    }


def _handle_email_class_spam(*, row: dict, triage_id: int, learned_by: str) -> str:
    """Q0 = SPAM: add sender domain to learned filter, log the event.

    Default match_type is 'domain' — mass-mailing lists rotate sender
    local-parts so blocking the whole domain catches future variants.
    Toby can curate exceptions manually via SQL if a domain is too
    broad (e.g. @gmail.com from one spam-prone contact).
    """
    from core.email_ingest.learned_filters import add_learned_filter
    sender = row.get('email_sender') or ''
    result = add_learned_filter(
        sender_raw=sender,
        classification='spam',
        match_type='domain',
        triage_id=triage_id,
        learned_by=learned_by,
    )
    return f'spam learned: {result.get("note", "?")}'


def _handle_email_class_personal(*, row: dict, triage_id: int, learned_by: str) -> str:
    """Q0 = PERSONAL: add sender EXACT email to learned filter.

    Personal contacts aren't mass-mailers — block just the one email,
    not the whole domain (often @gmail.com or similar).
    """
    from core.email_ingest.learned_filters import add_learned_filter
    sender = row.get('email_sender') or ''
    result = add_learned_filter(
        sender_raw=sender,
        classification='personal',
        match_type='exact',
        triage_id=triage_id,
        learned_by=learned_by,
    )
    return f'personal learned: {result.get("note", "?")}'


def _handle_email_class_new_enquiry(conn, *, row: dict, triage_id: int) -> str:
    """Q0 = NEW_ENQUIRY: write a memory chunk with the full email body
    so retrieval surfaces this enquiry next time.

    Doesn't auto-create a CRM project today — that path requires a
    confirmed project shape (client name, budget bucket, etc.) that
    only Toby has the context to set. Capturing the enquiry as a
    searchable memory is the cheap first cut; CRM-auto-creation is a
    separate brief if Toby later wants it.

    Body comes from cairn_email_raw via the email_message_id link on
    the triage row.
    """
    message_id = row.get('email_message_id')
    sender = row.get('email_sender') or '(unknown)'
    subject = row.get('email_subject') or '(no subject)'
    body_text = ''
    if message_id:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COALESCE(body_text, body_html, '')
                         FROM cairn_email_raw
                        WHERE message_id = %s
                        LIMIT 1""",
                    (message_id,),
                )
                row_body = cur.fetchone()
                if row_body:
                    body_text = (row_body[0] or '')[:4000]
        except Exception:
            body_text = ''

    memory_text = (
        f'New enquiry captured (triage {triage_id}).\n'
        f'From: {sender}\n'
        f'Subject: {subject}\n\n'
        f'{body_text}'
    )
    new_id = _write_toby_memory(
        conn, memory_text,
        reference_triage_id=triage_id,
        tag='triage_new_enquiry',
    )
    return f'new enquiry memory written (id={new_id})'


def _crm_db_url() -> str | None:
    """Build the CRM database connection string from Deek's DATABASE_URL.
    Same shape as scripts/email_triage/project_matcher._crm_db_url —
    duplicated here to keep replies.py self-contained for clarity.
    """
    url = os.getenv('DATABASE_URL', '')
    if not url or '/' not in url:
        return None
    return url.rsplit('/', 1)[0] + '/crm'


def _resolve_project_by_name_via_crm_db(name: str) -> dict | None:
    """Direct CRM DB lookup for a free-text project name.

    CRM's search API ranks badly for short queries — three projects can
    tie at the 0.014-0.016 cosine noise floor with no signal to
    discriminate. ILIKE against the structured columns is far more
    reliable when Toby types something specific like
    ``PROJECT: Flowers by Julie``. Matches:

      1. exact-substring on Project.name (case-insensitive)
      2. exact-substring on Project.clientName (case-insensitive)

    Most recently updated wins on ties. Returns the same dict shape as
    the search-API path so the caller treats them identically.
    """
    name_norm = (name or '').strip()
    if not name_norm:
        return None
    crm_url = _crm_db_url()
    if not crm_url:
        return None

    try:
        import psycopg2
        conn = psycopg2.connect(crm_url, connect_timeout=5)
    except Exception as exc:
        logger.warning('resolve_by_name: CRM DB connect failed: %s', exc)
        return None

    try:
        with conn.cursor() as cur:
            pattern = f'%{name_norm}%'
            cur.execute(
                '''
                SELECT id, name, "clientName", "clientEmail", "updatedAt"
                  FROM "Project"
                 WHERE name ILIKE %s OR "clientName" ILIKE %s
                 ORDER BY "updatedAt" DESC NULLS LAST
                 LIMIT 1
                ''',
                (pattern, pattern),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning('resolve_by_name: CRM DB query failed: %s', exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not row:
        return None
    project_id, proj_name, client_name, _email, _updated = row
    return {
        'project_id':   project_id,
        'project_name': proj_name or '',
        'match_score':  1.0,  # exact substring; not a fuzzy score
        'note':         f'resolved "{name_norm[:60]}" -> {proj_name[:60]} (via CRM DB)',
    }


def _resolve_project_by_name(typed_name: str) -> dict:
    """Resolve a free-text ``PROJECT: <name>`` override to a CRM project.

    Toby types something like ``PROJECT: Smith windows`` or
    ``PROJECT: M1234`` or ``PROJECT: Acme Ltd``.

    Resolution order:
      1. Direct CRM DB ILIKE on Project.name / Project.clientName
         (``_resolve_project_by_name_via_crm_db``) — the canonical
         path. Reliable for specific names even when CRM's search
         ranking is junk.
      2. CRM ``/api/cairn/search?q=<name>&types=project&limit=5``
         fallback — used when the DB is unreachable.

    Returns ``{'project_id': str, 'project_name': str, 'match_score':
    float, 'note': str}``. ``project_id`` is empty when nothing
    plausible came back; the note explains why.

    Updated 2026-05-12: added direct-DB primary path after CRM's
    search was confirmed not to index clientEmail / not to surface
    structured-column matches above the 0.014-0.016 noise floor.
    """
    out = {'project_id': '', 'project_name': '', 'match_score': 0.0, 'note': ''}
    name = (typed_name or '').strip()
    if not name:
        out['note'] = 'empty name'
        return out

    # Primary path — direct DB
    via_db = _resolve_project_by_name_via_crm_db(name)
    if via_db is not None:
        out.update(via_db)
        return out

    # Fallback — search API
    import httpx
    base = (os.getenv('CRM_BASE_URL') or 'https://crm.nbnesigns.co.uk').rstrip('/')
    token = (
        os.getenv('DEEK_API_KEY')
        or os.getenv('CAIRN_API_KEY')
        or os.getenv('CLAW_API_KEY', '')
    ).strip()
    if not token:
        out['note'] = 'no auth token + DB unavailable'
        return out
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(
                f'{base}/api/cairn/search',
                params={'q': name[:200], 'types': 'project', 'limit': 5},
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        out['note'] = f'CRM search failed: {exc}'
        return out
    if r.status_code != 200:
        out['note'] = f'HTTP {r.status_code}'
        return out
    try:
        results = (r.json() or {}).get('results') or []
    except Exception:
        out['note'] = 'malformed JSON'
        return out
    project_rows = [x for x in results if x.get('source_type') == 'project']
    if not project_rows:
        out['note'] = 'no project results'
        return out
    top = project_rows[0]
    md = top.get('metadata') or {}
    out['project_id'] = top.get('source_id', '')
    out['project_name'] = (
        md.get('project_name')
        or md.get('title')
        or top.get('title')
        or ''
    )
    out['match_score'] = float(top.get('score') or 0.0)
    out['note'] = f'resolved "{name[:60]}" -> {out["project_name"][:60]} (via search API)'
    return out


def _post_crm_note(
    project_id: str, message: str, source: str = 'triage_reply',
) -> str | None:
    """POST a note to the CRM via /api/cairn/memory. Returns the note
    id or None on any failure."""
    import httpx
    if not project_id:
        return None
    base = (os.getenv('CRM_BASE_URL') or 'https://crm.nbnesigns.co.uk').rstrip('/')
    token = (
        os.getenv('DEEK_API_KEY')
        or os.getenv('CAIRN_API_KEY')
        or os.getenv('CLAW_API_KEY', '')
    ).strip()
    if not token:
        return None
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                f'{base}/api/cairn/memory',
                json={
                    'type': 'note',
                    'priority': 'low',
                    'message': message[:3000],
                    'project_id': project_id,
                    'source_modules': ['deek', source],
                },
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        logger.warning('[triage-reply] CRM POST failed: %s', exc)
        return None
    if r.status_code not in (200, 201):
        logger.warning(
            '[triage-reply] CRM returned HTTP %d — %s',
            r.status_code, r.text[:200],
        )
        return None
    try:
        data = r.json()
    except Exception:
        return None
    return (data or {}).get('id')


def _patch_crm_project_folder(
    project_id: str, folder_path: str,
) -> dict:
    """Phase C: PATCH the CRM project with a dedicated folder column.

    Tries PATCH /api/cairn/projects/{id}/folder. Returns a summary
    dict:
      {'applied': bool, 'endpoint_available': bool, 'note': str}

    On 404/405 the CRM doesn't have the endpoint yet (Phase C brief
    not merged). We return endpoint_available=False and the caller
    falls back to embedding folder_path in the note body — the
    pre-Phase-C behaviour. No-ops on empty path or missing id.

    The probe is cheap (one HTTP round-trip per reply with a folder
    path set; that's at most a handful per day). Once the endpoint
    exists, every subsequent call succeeds cleanly.
    """
    import httpx
    out = {'applied': False, 'endpoint_available': False, 'note': ''}
    if not project_id or not folder_path or not folder_path.strip():
        out['note'] = 'no-op (empty id or path)'
        return out
    base = (os.getenv('CRM_BASE_URL') or 'https://crm.nbnesigns.co.uk').rstrip('/')
    token = (
        os.getenv('DEEK_API_KEY')
        or os.getenv('CAIRN_API_KEY')
        or os.getenv('CLAW_API_KEY', '')
    ).strip()
    if not token:
        out['note'] = 'no auth token'
        return out
    url = f'{base}/api/cairn/projects/{project_id}/folder'
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.patch(
                url,
                json={'localFolderPath': folder_path.strip()[:500]},
                headers={'Authorization': f'Bearer {token}'},
            )
    except Exception as exc:
        out['note'] = f'{type(exc).__name__}: {exc}'
        return out

    if r.status_code in (404, 405):
        # Phase C endpoint not live yet. Expected path today; caller
        # folds the folder_path into the note body instead.
        out['note'] = f'endpoint not available (HTTP {r.status_code})'
        return out
    out['endpoint_available'] = True
    if r.status_code in (200, 201, 204):
        out['applied'] = True
        out['note'] = 'folder path set on CRM project'
    else:
        out['note'] = f'CRM returned HTTP {r.status_code}: {r.text[:200]}'
    return out


def _mark_similar_job_useful(
    conn, triage_id: int, useful_index: int,
) -> int | None:
    """Flag the most recent triage_similarity_debug row for this
    triage_id with the candidate index Toby marked useful. Returns
    the debug row id, or None if no debug row exists (shadow mode
    was off when the digest went out, or the table hasn't been
    written yet).
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE cairn_intel.triage_similarity_debug
                     SET useful_index = %s,
                         useful_flagged_at = NOW()
                    WHERE id = (
                        SELECT id FROM cairn_intel.triage_similarity_debug
                         WHERE triage_id = %s
                         ORDER BY created_at DESC
                         LIMIT 1
                    )
                  RETURNING id""",
                (int(useful_index), int(triage_id)),
            )
            row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception as exc:
        logger.warning('[triage-reply] mark-useful failed: %s', exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def _write_toby_memory(
    conn, text: str, reference_triage_id: int,
    tag: str = 'triage_reply_note',
) -> int | None:
    """Mirror of core.brief.replies._write_toby_memory — new memory
    chunk with toby_flag=true, linked to the originating triage row."""
    if not text.strip():
        return None
    try:
        from core.wiki.embeddings import get_embed_fn
        embed_fn = get_embed_fn()
        emb = embed_fn(text[:6000]) if embed_fn else None
    except Exception as exc:
        logger.warning('[triage-reply] embed failed (non-fatal): %s', exc)
        emb = None

    content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    file_path = f'memory/{tag}/{content_hash[:16]}'
    signals = {
        'toby_flag': 1.0,
        'via': 'triage_reply',
        'triage_id': int(reference_triage_id),
        'tag': tag,
    }
    with conn.cursor() as cur:
        if emb is not None:
            cur.execute(
                """INSERT INTO claw_code_chunks
                    (project_id, file_path, chunk_content, chunk_type,
                     chunk_name, content_hash, embedding, indexed_at,
                     salience, salience_signals, last_accessed_at,
                     access_count)
                   VALUES ('deek', %s, %s, 'memory', %s, %s, %s::vector,
                           NOW(), 7.0, %s::jsonb, NOW(), 0)
                   RETURNING id""",
                (file_path, text, text[:200], content_hash, emb,
                 json.dumps(signals)),
            )
        else:
            cur.execute(
                """INSERT INTO claw_code_chunks
                    (project_id, file_path, chunk_content, chunk_type,
                     chunk_name, content_hash, indexed_at,
                     salience, salience_signals, last_accessed_at,
                     access_count)
                   VALUES ('deek', %s, %s, 'memory', %s, %s, NOW(),
                           7.0, %s::jsonb, NOW(), 0)
                   RETURNING id""",
                (file_path, text, text[:200], content_hash,
                 json.dumps(signals)),
            )
        (new_id,) = cur.fetchone()
    return int(new_id)


def apply_reply(conn, reply: ParsedReply, raw_body: str) -> dict:
    """Apply a parsed reply to the triage row + CRM + memory.

    Never raises. Returns a summary dict for logging / test assertions.
    """
    if reply.triage_id is None:
        return {'error': 'no triage_id provided', 'answers_processed': []}

    row = load_triage_row(conn, reply.triage_id)
    if row is None:
        return {'error': f'triage row {reply.triage_id} not found',
                'answers_processed': []}

    summary: dict = {
        'triage_id': reply.triage_id,
        'answers_processed': [],
        'parse_notes': reply.parse_notes,
    }

    # Compute the final project_id + approved_reply + project_folder from
    # the answers so we can write the triage row update in one UPDATE.
    final_project_id = row['project_id']
    approved_reply = row.get('draft_reply') or ''
    project_folder_path = ''
    review_action = 'reviewed'

    # ── Q0 (email_classification) pre-scan ─────────────────────────────
    # Spam / personal / new_enquiry short-circuit the rest of the
    # reply processing — if Toby flagged this as spam, we don't want
    # to also try to confirm a project match (likely empty), post a
    # CRM note, or persist a thread association. New_enquiry captures
    # the email body as a training-signal memory and skips the
    # project-confirm path. EXISTING (or empty Q0) falls through to
    # the legacy single-question flow so behaviour is unchanged for
    # the dominant case. Added 2026-05-08.
    q0_short_circuit = False
    for ans in reply.answers:
        if ans.category != 'email_classification':
            continue
        action: dict = {
            'q_number': ans.q_number,
            'category': ans.category,
            'verdict': ans.verdict,
        }
        try:
            if ans.verdict == 'spam':
                action['result'] = _handle_email_class_spam(
                    row=row, triage_id=reply.triage_id,
                    learned_by=reply.user_email,
                )
                review_action = 'ignored_spam'
                final_project_id = None
                approved_reply = ''
                q0_short_circuit = True
            elif ans.verdict == 'personal':
                action['result'] = _handle_email_class_personal(
                    row=row, triage_id=reply.triage_id,
                    learned_by=reply.user_email,
                )
                review_action = 'ignored_personal'
                final_project_id = None
                approved_reply = ''
                q0_short_circuit = True
            elif ans.verdict == 'new_enquiry':
                action['result'] = _handle_email_class_new_enquiry(
                    conn, row=row, triage_id=reply.triage_id,
                )
                review_action = 'new_enquiry_captured'
                final_project_id = None
                approved_reply = ''
                # Don't short-circuit — Q1 may still carry a follow-up
                # PROJECT: hint if Toby wants to nominate a project name
                # for the future. Treat as additive context.
            elif ans.verdict == 'ignore':
                action['result'] = 'ignored (no learning signal)'
                review_action = 'ignored'
                final_project_id = None
                approved_reply = ''
                q0_short_circuit = True
            elif ans.verdict == 'existing':
                # Default path — let Q1 take over
                action['result'] = 'existing (pass-through to Q1)'
            elif ans.verdict == 'empty':
                action['result'] = 'empty (implicit existing)'
            else:
                # 'text' verdict — free text that wasn't a known token
                action['result'] = (
                    f'free-text Q0 (no learning rule): '
                    f'{(ans.free_text or "")[:80]}'
                )
                _write_toby_memory(
                    conn,
                    f'Q0 free-text on triage {reply.triage_id}: {ans.free_text}',
                    reference_triage_id=reply.triage_id,
                    tag='triage_q0_freetext',
                )
        except Exception as exc:
            action['error'] = f'{type(exc).__name__}: {exc}'
            logger.warning('[triage-reply] Q0 handler failure: %s', exc)
        summary['answers_processed'].append(action)

    for ans in reply.answers:
        if ans.category == 'email_classification':
            continue  # already handled in pre-scan
        if q0_short_circuit and ans.category in ('match_confirm', 'reply_approval'):
            # Don't second-guess spam/personal/ignore — skip Q1/Q2 entirely
            summary['answers_processed'].append({
                'q_number': ans.q_number,
                'category': ans.category,
                'verdict':  ans.verdict,
                'result':   'skipped (Q0 short-circuit)',
            })
            continue
        action: dict = {
            'q_number': ans.q_number,
            'category': ans.category,
            'verdict': ans.verdict,
        }
        try:
            if ans.category == 'match_confirm':
                if ans.verdict == 'affirm':
                    # YES = candidate #1 is correct. If project_id
                    # was None (match was below confidence threshold
                    # but Toby confirmed it anyway), fall through to
                    # candidates[0] so downstream actions have a
                    # project to attach to.
                    if not final_project_id:
                        cands = row.get('match_candidates') or []
                        if cands:
                            final_project_id = cands[0].get('project_id') or final_project_id
                    action['result'] = f'confirmed project_id={final_project_id}'
                    # Phase A thread-association: persist this match
                    # so the NEXT message on the same thread
                    # auto-attaches without going through triage.
                    _persist_thread_association(
                        conn, reply.triage_id, final_project_id,
                        reply.user_email,
                        source='triage_reply_yes',
                        action_dict=action,
                    )
                elif ans.verdict == 'select_candidate':
                    idx = ans.selected_candidate_index or 1
                    cands = row.get('match_candidates') or []
                    if 1 <= idx <= len(cands):
                        final_project_id = cands[idx - 1].get('project_id') or final_project_id
                        action['result'] = (
                            f'selected candidate #{idx}: {final_project_id}'
                        )
                        _persist_thread_association(
                            conn, reply.triage_id, final_project_id,
                            reply.user_email,
                            source='triage_reply_yes',
                            action_dict=action,
                        )
                    else:
                        action['result'] = f'invalid candidate #{idx}'
                elif ans.verdict == 'select_project':
                    # `PROJECT: <name>` override — Toby is correcting
                    # the match because none of the 3 candidates fit.
                    # Resolve via CRM search; on hit, set as the new
                    # project_id and persist the thread association so
                    # future emails on the same thread auto-route here.
                    typed = ans.free_text or ''
                    resolved = _resolve_project_by_name(typed)
                    if resolved.get('project_id'):
                        final_project_id = resolved['project_id']
                        action['result'] = (
                            f'PROJECT override: "{typed[:60]}" -> '
                            f'{resolved.get("project_name", "?")[:60]} '
                            f'(id={final_project_id}, '
                            f'score={resolved.get("match_score", 0.0):.3f})'
                        )
                        _persist_thread_association(
                            conn, reply.triage_id, final_project_id,
                            reply.user_email,
                            source='triage_reply_project_override',
                            action_dict=action,
                        )
                        # Memory chunk so the corrected mapping is
                        # searchable as a learning signal.
                        _write_toby_memory(
                            conn,
                            f'PROJECT override on triage {reply.triage_id}: '
                            f'"{typed}" -> {resolved.get("project_name", "?")}',
                            reference_triage_id=reply.triage_id,
                            tag='triage_project_override',
                        )
                    else:
                        action['result'] = (
                            f'PROJECT: "{typed[:60]}" — could not resolve '
                            f'({resolved.get("note", "?")})'
                        )
                        _write_toby_memory(
                            conn,
                            f'PROJECT override on triage {reply.triage_id} '
                            f'failed to resolve "{typed}". CRM note: '
                            f'{resolved.get("note", "?")}.',
                            reference_triage_id=reply.triage_id,
                            tag='triage_project_override_unresolved',
                        )
                elif ans.verdict == 'deny':
                    # Toby rejected the match — clear confirmed project
                    final_project_id = None
                    action['result'] = 'cleared project_id (rejected match)'
                elif ans.verdict == 'text':
                    # Free-text correction — captured but not auto-applied
                    action['result'] = 'free-text match correction captured'
                    _write_toby_memory(
                        conn, f'Match correction on triage {reply.triage_id}: {ans.free_text}',
                        reference_triage_id=reply.triage_id,
                        tag='triage_match_correction',
                    )
                else:
                    action['result'] = 'empty; no change'

            elif ans.category == 'reply_approval':
                if ans.verdict == 'affirm':
                    action['result'] = 'approved draft as-is'
                elif ans.verdict == 'edit':
                    approved_reply = ans.edited_text or approved_reply
                    action['result'] = 'approved edited reply'
                elif ans.verdict == 'deny':
                    approved_reply = ''  # don't post a rejected draft
                    action['result'] = 'draft rejected; no CRM note'
                else:
                    action['result'] = 'empty; keeping existing draft'

            elif ans.category == 'project_folder':
                if ans.verdict == 'text' and ans.free_text:
                    project_folder_path = ans.free_text
                    action['result'] = f'set project folder'
                else:
                    action['result'] = 'empty; no folder recorded'

            elif ans.category == 'similar_job_useful':
                # Phase D learning signal. Store on the
                # triage_similarity_debug row so Phase E can aggregate
                # across all digests. Also write a toby-flagged memory
                # chunk so retrieval picks it up.
                if ans.verdict == 'select_candidate':
                    idx = ans.selected_candidate_index or 0
                    marked = _mark_similar_job_useful(
                        conn, reply.triage_id, idx,
                    )
                    action['result'] = (
                        f'marked similar job #{idx} useful '
                        f'(debug_row={marked})'
                    )
                    _write_toby_memory(
                        conn,
                        f'Similar past job #{idx} flagged useful by Toby '
                        f'for triage {reply.triage_id}.',
                        reference_triage_id=reply.triage_id,
                        tag='triage_similarity_useful',
                    )
                elif ans.verdict == 'text':
                    _write_toby_memory(
                        conn,
                        f'Similar-jobs free-text on triage '
                        f'{reply.triage_id}: {ans.free_text}',
                        reference_triage_id=reply.triage_id,
                        tag='triage_similarity_note',
                    )
                    action['result'] = 'similarity free-text captured'
                else:
                    action['result'] = 'empty; no similarity signal'

            elif ans.category == 'notes':
                if ans.verdict == 'text' and ans.free_text:
                    new_id = _write_toby_memory(
                        conn, ans.free_text,
                        reference_triage_id=reply.triage_id,
                        tag='triage_note',
                    )
                    action['result'] = f'wrote memory {new_id}'
                    action['new_memory_id'] = new_id
                else:
                    action['result'] = 'empty'

            else:
                action['result'] = 'unknown category; skipped'

        except Exception as exc:
            action['error'] = f'{type(exc).__name__}: {exc}'
            logger.warning('[triage-reply] per-answer failure: %s', exc)

        summary['answers_processed'].append(action)

    # Phase C: if there's a folder path, try the dedicated CRM
    # endpoint first. On 404/405 (endpoint not deployed yet), the
    # folder path folds into the note body as Phase B did.
    folder_handled_by_patch = False
    if final_project_id and project_folder_path:
        patch_result = _patch_crm_project_folder(
            final_project_id, project_folder_path,
        )
        summary['crm_folder_patch'] = patch_result
        folder_handled_by_patch = patch_result.get('applied', False)

    # CRM note: post the approved reply (and the folder path, if it
    # wasn't already handled by the dedicated endpoint).
    crm_note_id: str | None = None
    if final_project_id and approved_reply:
        parts = ['Approved reply (sent by Toby):\n\n' + approved_reply.strip()]
        if project_folder_path and not folder_handled_by_patch:
            parts.append(f'Project folder: {project_folder_path}')
        note_body = '\n\n'.join(parts)
        crm_note_id = _post_crm_note(final_project_id, note_body)
        summary['crm_note_id'] = crm_note_id
    elif final_project_id and project_folder_path and not folder_handled_by_patch:
        # Folder-only update, no approved reply — and the dedicated
        # endpoint wasn't available, so fall back to a note.
        crm_note_id = _post_crm_note(
            final_project_id, f'Project folder: {project_folder_path}',
        )
        summary['crm_note_id'] = crm_note_id

    # Update the triage row — single UPDATE so the state is atomic.
    digest_tag = f'sha256:{_body_hash(raw_body, reply.triage_id)}'
    review_notes_combined = digest_tag
    # Stash a brief human summary too so future inspection is easy
    verdicts = [a.get('verdict') for a in summary['answers_processed']]
    review_notes_combined += f' | verdicts={verdicts}'

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE cairn_intel.email_triage
                  SET project_id = %s,
                      draft_reply = CASE
                          WHEN %s = '' THEN draft_reply
                          ELSE %s
                      END,
                      project_folder_path = COALESCE(NULLIF(%s, ''), project_folder_path),
                      reviewed_at = NOW(),
                      review_action = %s,
                      review_notes = %s
                WHERE id = %s""",
            (
                final_project_id,
                approved_reply, approved_reply,
                project_folder_path,
                review_action,
                review_notes_combined,
                reply.triage_id,
            ),
        )
    conn.commit()

    summary['applied'] = True
    summary['final_project_id'] = final_project_id
    summary['approved_reply_length'] = len(approved_reply)
    summary['project_folder_path'] = project_folder_path
    return summary


__all__ = [
    'ParsedAnswer', 'ParsedReply',
    'is_triage_reply', 'strip_reply_prefix',
    'match_triage_row_by_subject', 'strip_quoted',
    'parse_reply_body', 'apply_reply',
    'already_applied', 'load_triage_row',
]
