"""
Ongoing inbox processor.

Polls a configured IMAP mailbox every 15 minutes (via cron / Scheduled
Task). Classifies incoming mail into two types:

    Type 1 — Forwarded business email
        Sender is sales@ or toby@, or subject contains 'Fwd:'.
        Standard ingest + embed. Label: forwarded_business.

    Type 2 — Direct notes
        Sent directly to the mailbox, not forwarded.
        Ingest + embed immediately (higher priority).
        Labels: direct_note, wiki_candidate.

The mailbox is parameterised: cairn@ (NBNE-Deek), jo@ (Rex), etc. The
processor is the same; the DB it writes to differs by container env
(jo-pip's own Postgres for Rex, Hetzner's for cairn@).
"""
import logging
from datetime import datetime, timezone

from core.email_ingest.db import get_conn
from core.email_ingest.filters import should_skip_email, sanitise_email_content
from core.email_ingest.imap_client import (
    connect_imap,
    fetch_all_uids,
    fetch_message,
    parse_message,
)
from core.email_ingest.embedder import embed_email_batch

logger = logging.getLogger(__name__)

DEEK_INBOX = 'cairn'  # legacy default — kept for backwards compat

# Senders whose forwarded mail should be treated as business email
FORWARDING_SOURCES = {
    'sales@nbnesigns.co.uk',
    'toby@nbnesigns.com',
}


def _classify_labels(parsed: dict) -> list[str]:
    """Return labels list based on sender and subject."""
    sender = (parsed['sender'] or '').lower()
    subject = (parsed['subject'] or '').lower()

    is_forwarded = (
        sender in {s.lower() for s in FORWARDING_SOURCES}
        or subject.startswith('fwd:')
        or subject.startswith('fw:')
    )
    if is_forwarded:
        return ['forwarded_business']

    # Direct note to Deek
    return ['direct_note', 'wiki_candidate']


def _load_known_ids(mailbox: str = DEEK_INBOX) -> set[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT message_id FROM cairn_email_raw WHERE mailbox=%s",
                (mailbox,),
            )
            return {row[0] for row in cur.fetchall()}


def _store_email(parsed: dict, labels: list[str]) -> bool:
    """Upsert email into cairn_email_raw. Returns True if newly inserted."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cairn_email_raw
                    (message_id, mailbox, sender, recipients, subject,
                     body_text, body_html, received_at, thread_id, labels,
                     is_embedded, skip_reason, word_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, FALSE, NULL, %s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (
                    parsed['message_id'],
                    parsed['mailbox'],
                    parsed['sender'],
                    parsed['recipients'],
                    parsed['subject'],
                    parsed['body_text'],
                    parsed['body_html'],
                    parsed['received_at'],
                    parsed['thread_id'],
                    labels,
                    parsed['word_count'],
                ),
            )
            inserted = cur.rowcount == 1
            conn.commit()
    return inserted


def process_inbox(
    mailbox: str = DEEK_INBOX,
    embed_immediately: bool = True,
) -> dict:
    """
    Check the named mailbox for new messages, ingest and embed them.

    The mailbox name must exist in
    ``core.email_ingest.imap_client.MAILBOX_CONFIG``. Cron entries call
    one of:

        * ``process_deek_inbox.py`` → mailbox='cairn' (NBNE-Deek)
        * ``process_jo_inbox.py``   → mailbox='jo' (Rex / jo-pip)

    Each writes to the DB in its own container's DATABASE_URL — Rex's
    isolated Postgres for jo's mail, Hetzner's for cairn@.

    Returns summary: {new_messages, forwarded, direct_notes,
    wiki_candidates, errors}.
    """
    log_prefix = f'[{mailbox}@]'
    logger.info('%s Processing inbox', log_prefix)
    known_ids = _load_known_ids(mailbox)

    new_messages = 0
    forwarded = 0
    direct_notes = 0
    wiki_candidates = 0
    errors = 0

    try:
        imap = connect_imap(mailbox)
    except (EnvironmentError, KeyError) as exc:
        logger.error('%s Cannot connect: %s', log_prefix, exc)
        return {'status': 'error', 'reason': str(exc)}

    try:
        uids = fetch_all_uids(imap, 'INBOX')
        logger.info('%s %d messages in inbox', log_prefix, len(uids))

        for uid in uids:
            try:
                msg = fetch_message(imap, uid)
                if msg is None:
                    errors += 1
                    continue

                parsed = parse_message(msg, mailbox)

                if not parsed['message_id']:
                    import hashlib
                    parsed['message_id'] = (
                        f'<synthetic-{mailbox}-{uid.decode()}-'
                        f'{hashlib.md5((parsed.get("subject") or "").encode()).hexdigest()[:8]}@{mailbox}>'
                    )

                if parsed['message_id'] in known_ids:
                    continue

                skip, skip_reason = should_skip_email(
                    parsed['sender'] or '', parsed['subject'] or ''
                )
                if skip:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO cairn_email_raw
                                    (message_id, mailbox, sender, subject, recipients,
                                     is_embedded, skip_reason, word_count)
                                VALUES (%s,%s,%s,%s,'{}', FALSE, %s, 0)
                                ON CONFLICT (message_id) DO NOTHING
                                """,
                                (
                                    parsed['message_id'], mailbox,
                                    parsed['sender'], parsed['subject'], skip_reason,
                                ),
                            )
                            conn.commit()
                    known_ids.add(parsed['message_id'])
                    continue

                # Sanitise before storage
                if parsed['body_text']:
                    parsed['body_text'] = sanitise_email_content(parsed['body_text'])
                if parsed['subject']:
                    parsed['subject'] = sanitise_email_content(parsed['subject'])

                labels = _classify_labels(parsed)
                inserted = _store_email(parsed, labels)

                if inserted:
                    known_ids.add(parsed['message_id'])
                    new_messages += 1

                    if 'forwarded_business' in labels:
                        forwarded += 1
                    if 'direct_note' in labels:
                        direct_notes += 1
                    if 'wiki_candidate' in labels:
                        wiki_candidates += 1

                    logger.info(
                        '%s New: %s | labels=%s',
                        log_prefix, parsed['subject'], labels,
                    )

            except Exception as exc:
                logger.error('%s Error processing uid=%s: %s', log_prefix, uid, exc, exc_info=True)
                errors += 1

    finally:
        try:
            imap.logout()
        except Exception:
            pass

    # Embed newly ingested messages
    if embed_immediately and new_messages > 0:
        logger.info('%s Embedding %d new messages', log_prefix, new_messages)
        try:
            embed_result = embed_email_batch(batch_size=new_messages + 10)
            logger.info('%s Embed result: %s', log_prefix, embed_result)
        except Exception as exc:
            logger.error('%s Embedding failed: %s', log_prefix, exc)

    result = {
        'status': 'complete',
        'mailbox': mailbox,
        'new_messages': new_messages,
        'forwarded': forwarded,
        'direct_notes': direct_notes,
        'wiki_candidates': wiki_candidates,
        'errors': errors,
    }
    logger.info('%s Done: %s', log_prefix, result)
    return result


def process_deek_inbox(embed_immediately: bool = True) -> dict:
    """Backwards-compatible alias — processes the cairn@ mailbox.

    Existing callers (scripts/process_deek_inbox.py + the Hetzner
    cron) use this name. New mailboxes should call process_inbox()
    directly with their mailbox name.
    """
    return process_inbox(mailbox=DEEK_INBOX, embed_immediately=embed_immediately)
