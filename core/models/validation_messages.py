"""User-safe translations of validator rejections + retry guidance.

The OutputValidator emits structured failure strings like
``'CHECK 3: hallucinated file path "core/memory/brief_questions.py"'``.
These are useful for logs and for the retry prompt, but must never
reach the user — leaking internal check numbers and exception
excerpts has been a persistent UX problem (see briefs/validator-leak-
and-contamination-fix.md).

This module is the single source of truth for:

  1. translating CHECK codes to plain-language user reasons
     (``user_reason_for_failures``)
  2. assembling the per-turn retry guidance that is included in the
     recovery prompt sent back to the model
     (``retry_guidance_for_failures``)

Kept as a pure module — no I/O, no logging — so it is trivially
tested and can be imported by ``core.agent`` without circularity.
"""
from __future__ import annotations

import re

# ── Plain-language reasons, for the user-facing fallback ─────────────
#
# Map a CHECK number to ONE short sentence the user can understand.
# When a response fails multiple checks we use ``_MULTI_REASON``.
# When something that isn't a CHECK (e.g. a timeout) needs user-safe
# framing, call ``user_reason_for_timeout`` / ``user_reason_for_error``.

_CHECK_REASONS: dict[int, str] = {
    1: 'I described a tool call without actually running it.',
    2: 'I refused rather than answered.',
    3: "I cited a file I couldn't verify.",
    4: "The draft didn't pass a tenant-isolation check.",
    5: 'The response came back effectively empty.',
    6: 'A file I wrote has a Python syntax error.',
}

_MULTI_REASON = 'The draft failed multiple quality checks.'
_UNKNOWN_REASON = "I couldn't finish the response confidently."

# ── Per-CHECK guidance, for the retry prompt back to the model ───────

_CHECK_GUIDANCE: dict[int, str] = {
    1: (
        'Your previous response described a tool call in prose but did '
        'not execute any tool. If you need a tool, call it; otherwise '
        'produce the response without narrating hypothetical tool use.'
    ),
    2: (
        'Your previous response refused or deflected. Answer the user '
        'directly with the information already in context; do not '
        'prepend apologies about capability.'
    ),
    3: (
        'Your previous response cited a file path that does not exist. '
        'Produce the response again without citing specific files or '
        'paths unless you have verified they exist via a tool call.'
    ),
    4: (
        'Your previous response included an ORM query without a tenant '
        'filter nearby. Rewrite the code so every queryset filters on '
        'tenant, or state that the query must be scoped by tenant.'
    ),
    5: (
        'Your previous response was empty or trivially short. Produce '
        'a complete answer to the user, using the tool results already '
        'in context.'
    ),
    6: (
        'A file you wrote had a Python syntax error. Re-issue the edit '
        'with valid syntax, paying attention to indentation, matched '
        'parentheses, and unterminated strings.'
    ),
}

_CHECK_CODE_RE = re.compile(r'^CHECK\s+(\d+)\b', re.IGNORECASE)


def _check_numbers_in(failures: list[str]) -> list[int]:
    """Pull the CHECK numbers out of the validator's failure strings.

    Preserves order, deduplicates. Unknown / unparseable failures are
    silently skipped — they still get a generic fallback reason
    downstream.
    """
    seen: list[int] = []
    for f in failures or []:
        m = _CHECK_CODE_RE.match((f or '').strip())
        if not m:
            continue
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def user_reason_for_failures(failures: list[str]) -> str:
    """Turn a list of validator failure strings into ONE user-safe
    sentence. Never mentions CHECK codes, check names, or file paths.
    """
    nums = _check_numbers_in(failures)
    if not nums:
        return _UNKNOWN_REASON
    if len(nums) == 1:
        return _CHECK_REASONS.get(nums[0], _UNKNOWN_REASON)
    known = [_CHECK_REASONS[n] for n in nums if n in _CHECK_REASONS]
    if not known:
        return _UNKNOWN_REASON
    return _MULTI_REASON


def user_reason_for_timeout() -> str:
    return 'The model took too long to respond.'


def user_reason_for_error(_exc: BaseException | None = None) -> str:
    # Deliberately ignores the exception details — we never leak
    # exception class names or messages to the user.
    return "Something went wrong while I was preparing the response."


def user_facing_fallback(reason: str) -> str:
    """Assemble the final user-facing sentence."""
    return (
        "I wasn't able to produce a confident response this time "
        f"({reason}). Could you rephrase or narrow the question? "
        "I'll try again."
    )


def retry_guidance_for_failures(failures: list[str]) -> str:
    """Build the per-CHECK guidance block appended to the retry prompt.

    Unknown failures produce a generic nudge. Empty input produces an
    empty string — the caller decides whether to retry at all in that
    case.
    """
    nums = _check_numbers_in(failures)
    if not nums:
        return ''
    bullets = []
    for n in nums:
        g = _CHECK_GUIDANCE.get(n)
        if g:
            bullets.append(f'- {g}')
    if not bullets:
        return ''
    return (
        'The previous response failed post-response validation. '
        'Specific guidance:\n' + '\n'.join(bullets)
    )


__all__ = [
    'user_reason_for_failures',
    'user_reason_for_timeout',
    'user_reason_for_error',
    'user_facing_fallback',
    'retry_guidance_for_failures',
]
