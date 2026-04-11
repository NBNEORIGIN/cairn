"""
PII scrubbing for email + b2b_quote sources.

Pass 1 (regex) is implemented here for Phase 2 so the pipeline's
``needs_privacy_scrub`` path has something to call. Pass 2 (Haiku
rewrite) is wired in Phase 7 when the email source is built — at
that point the pipeline passes an ``ArchetypeTagger`` reference and
``scrub()`` grows a second argument.

The regex pass handles:
    - email addresses          → [EMAIL_REDACTED]
    - UK phone numbers         → [PHONE_REDACTED]
    - UK postcodes             → [POSTCODE_REDACTED]
    - UK VAT numbers           → [VAT_REDACTED]
    - UK National Insurance    → [NI_REDACTED]
"""
from __future__ import annotations

import re


_EMAIL_RE = re.compile(r'[\w\.\+\-]+@[\w\-]+(?:\.[\w\-]+)+')
# UK phone: +44 prefix or leading 0, 10-11 digits with optional spaces/hyphens
_PHONE_RE = re.compile(
    r'(?:\+44\s?|\(?0)(?:\d\s?){9,10}',
)
# UK postcode: AA9A 9AA / A9A 9AA / A9 9AA / A99 9AA / AA9 9AA / AA99 9AA
_POSTCODE_RE = re.compile(
    r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b',
    re.IGNORECASE,
)
# UK VAT: GB followed by 9 or 12 digits
_VAT_RE = re.compile(r'\bGB\s?\d{9}(?:\d{3})?\b', re.IGNORECASE)
# UK NI: 2 letters, 6 digits, 1 letter (often with spaces)
_NI_RE = re.compile(
    r'\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b',
    re.IGNORECASE,
)


def scrub(text: str) -> str:
    """Apply the Pass 1 regex scrub to a block of text.

    The result is safe to store in ``decisions.context_summary`` for
    email + b2b_quote rows. The raw original should be preserved in
    ``decisions.raw_source_ref.original_text`` by the source adapter.
    """
    if not text:
        return text
    text = _EMAIL_RE.sub('[EMAIL_REDACTED]', text)
    text = _PHONE_RE.sub('[PHONE_REDACTED]', text)
    text = _POSTCODE_RE.sub('[POSTCODE_REDACTED]', text)
    text = _VAT_RE.sub('[VAT_REDACTED]', text)
    text = _NI_RE.sub('[NI_REDACTED]', text)
    return text
