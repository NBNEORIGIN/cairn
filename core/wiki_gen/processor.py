"""
Wiki generation processors.

    process_direct_notes()     — generate articles from wiki_candidate emails
    process_wiki_candidates()  — alias used by scheduled task + API endpoint
"""
import logging

from core.wiki_gen.db import get_conn
from core.wiki_gen.generator import (
    subject_to_title,
    classify_module,
    quality_check,
    write_wiki_article,
    log_generation,
    call_claude,
)

logger = logging.getLogger(__name__)

_DIRECT_NOTE_PROMPT = """You are writing a wiki article for NBNE's internal Deek knowledge base.
The article should be structured, practical, and written from the perspective of an
experienced NBNE operator.

Source email:
Subject: {subject}
Body: {body}

Write a wiki article with:
- A clear title (from the subject)
- A one-paragraph summary
- Numbered steps or structured sections as appropriate
- Any warnings or common pitfalls highlighted
- Related topics the reader might also want to check

Format: Markdown. Maximum 800 words. No preamble. Start with the title as an H1.
"""


def _fetch_unprocessed_candidates() -> list[dict]:
    """Fetch all wiki_candidate emails not yet marked wiki_generated."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, subject, body_text, sender, received_at
                FROM cairn_email_raw
                WHERE labels @> ARRAY['wiki_candidate']
                  AND NOT (labels @> ARRAY['wiki_generated'])
                  AND skip_reason IS NULL
                  AND body_text IS NOT NULL
                ORDER BY received_at DESC
                """
            )
            rows = cur.fetchall()
    return [
        {
            'id': r[0],
            'subject': r[1] or '',
            'body_text': r[2] or '',
            'sender': r[3] or '',
            'received_at': r[4],
        }
        for r in rows
    ]


def _mark_wiki_generated(email_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cairn_email_raw "
                "SET labels = array_append(labels, 'wiki_generated') "
                "WHERE id = %s",
                (email_id,),
            )
            conn.commit()


def process_direct_notes() -> dict:
    """
    Generate wiki articles from all unprocessed wiki_candidate emails.
    Called by the scheduled task and the API endpoint.

    Returns summary: {processed, generated, failed_quality, errors, total_tokens}
    """
    candidates = _fetch_unprocessed_candidates()
    logger.info('process_direct_notes: %d unprocessed candidates', len(candidates))

    processed = 0
    generated = 0
    failed_quality = 0
    errors = 0
    total_tokens = 0

    for email in candidates:
        email_id = email['id']
        subject = email['subject']
        body = email['body_text']

        if len(body.split()) < 30:
            logger.warning(
                'Direct note id=%d "%s" too short (%d words) — skipping',
                email_id, subject, len(body.split()),
            )
            log_generation(
                source_type='direct_note',
                topic=subject,
                source_email_ids=[email_id],
                article_title=subject_to_title(subject),
                wiki_filename=None,
                quality_passed=False,
                quality_reason='source_too_short',
                chunk_count=1,
                tokens_used=0,
            )
            _mark_wiki_generated(email_id)
            processed += 1
            continue

        # Generate article
        prompt = _DIRECT_NOTE_PROMPT.format(subject=subject, body=body[:4000])
        try:
            article_text, gen_tokens = call_claude(prompt, max_tokens=2048)
        except Exception as exc:
            logger.error('Generation failed for email id=%d: %s', email_id, exc)
            errors += 1
            continue

        # Extract title from first H1
        lines = article_text.strip().splitlines()
        raw_title = lines[0].lstrip('#').strip() if lines else subject_to_title(subject)
        article_title = raw_title or subject_to_title(subject)

        # Quality gate
        passed, reason, qa_tokens = quality_check(article_text)
        total_tokens += gen_tokens + qa_tokens

        if not passed:
            logger.warning(
                'Quality gate failed for direct note id=%d "%s": %s',
                email_id, article_title, reason,
            )
            failed_quality += 1
            log_generation(
                source_type='direct_note',
                topic=subject,
                source_email_ids=[email_id],
                article_title=article_title,
                wiki_filename=None,
                quality_passed=False,
                quality_reason=reason,
                chunk_count=1,
                tokens_used=gen_tokens + qa_tokens,
            )
            _mark_wiki_generated(email_id)
            processed += 1
            continue

        # Write to disk + embed
        module = classify_module(article_title, article_text)
        try:
            import os
            wiki_path = write_wiki_article(article_title, article_text, module, email_id)
            wiki_filename = os.path.basename(wiki_path)
        except Exception as exc:
            logger.error('write_wiki_article failed for email id=%d: %s', email_id, exc)
            errors += 1
            continue

        log_generation(
            source_type='direct_note',
            topic=subject,
            source_email_ids=[email_id],
            article_title=article_title,
            wiki_filename=wiki_filename,
            quality_passed=True,
            quality_reason=reason,
            chunk_count=1,
            tokens_used=gen_tokens + qa_tokens,
        )
        _mark_wiki_generated(email_id)

        processed += 1
        generated += 1
        logger.info(
            'Generated direct note article: "%s" [%s]', article_title, module
        )

    result = {
        'processed': processed,
        'generated': generated,
        'failed_quality': failed_quality,
        'errors': errors,
        'total_tokens': total_tokens,
    }
    logger.info('process_direct_notes complete: %s', result)
    return result


# Alias used by scheduled task and API endpoint
process_wiki_candidates = process_direct_notes
