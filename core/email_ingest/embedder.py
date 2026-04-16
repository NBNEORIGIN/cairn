"""
Embedding pipeline for stored emails.

Reads from cairn_email_raw (is_embedded=FALSE, skip_reason IS NULL),
chunks each email body into 500-word windows, embeds each chunk using
the Cairn CodeIndexer embed() method, and writes to claw_code_chunks.

Key design decisions:
    - One DB connection per call; all chunk inserts for a single email
      share that connection and commit together (not per-chunk).
    - Deduplication via content_hash + WHERE NOT EXISTS.
    - Uses file_path='email/{mailbox}/{email_id}' and chunk_type='email'.
    - subject stored in chunk_name; subproject_id='email'.
"""
import hashlib
import json
import logging
import os
from datetime import datetime

from core.email_ingest.db import get_conn, get_db_url

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 1500
EMBED_PROJECT_ID = 'deek'


def _chunk_email(body_text: str, window_words: int = 500, overlap_words: int = 50) -> list[str]:
    """
    Split email body into word-windowed chunks with overlap.
    Returns list of text chunks.
    """
    if not body_text:
        return []
    words = body_text.split()
    if not words:
        return []
    step = max(1, window_words - overlap_words)
    chunks = []
    for start in range(0, len(words), step):
        chunk = ' '.join(words[start:start + window_words])
        if not chunk.strip():
            continue
        if len(chunk) > MAX_CHUNK_CHARS:
            chunk = chunk[:MAX_CHUNK_CHARS]
        chunks.append(chunk)
    return chunks


_indexer = None


def _get_indexer():
    """Singleton CodeIndexer — avoids reconnecting on every batch call."""
    global _indexer
    if _indexer is None:
        from core.context.indexer import CodeIndexer
        _indexer = CodeIndexer(
            project_id=EMBED_PROJECT_ID,
            codebase_path=os.getenv('DEEK_DATA_DIR') or os.getenv('CLAW_DATA_DIR', 'D:/deek'),
            db_url=get_db_url(),
        )
    return _indexer


def embed_email_batch(batch_size: int = 200) -> dict:
    """
    Embed up to batch_size stored emails into claw_code_chunks.

    Uses embed_batch() so OpenAI processes up to 100 chunks per API call —
    dramatically faster than one embed() call per chunk.

    Strategy:
      1. Fetch batch_size emails from cairn_email_raw
      2. Chunk each email body
      3. Build content strings + content_hashes for all chunks
      4. Filter out already-embedded hashes (single bulk query)
      5. embed_batch() all remaining content strings in one call
      6. INSERT all rows + mark emails as embedded

    Safe to call repeatedly — is_embedded + content_hash prevent double work.
    """
    from pgvector.psycopg2 import register_vector

    indexer = _get_indexer()
    embedded = 0
    errors = 0
    chunks_written = 0

    with get_conn() as conn:
        register_vector(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, mailbox, sender, subject, body_text, received_at
                FROM cairn_email_raw
                WHERE is_embedded = FALSE AND skip_reason IS NULL
                ORDER BY received_at DESC
                LIMIT %s
                """,
                (batch_size,),
            )
            emails = cur.fetchall()

        if not emails:
            return {'embedded': 0, 'errors': 0, 'chunks_written': 0}

        logger.info('embed_email_batch: %d emails to process', len(emails))

        # ── Phase 1: build all (email_id, chunk_index, content, content_hash) ──
        all_items = []  # (email_id, mailbox, subject, received_at, chunk_index, content, hash)
        empty_email_ids = []

        for row in emails:
            email_id, mailbox, sender, subject, body_text, received_at = row
            chunks = _chunk_email(body_text or '')

            if not chunks:
                empty_email_ids.append(email_id)
                continue

            date_str = received_at.date().isoformat() if received_at else 'unknown'
            for chunk_index, chunk in enumerate(chunks):
                content = (
                    f'Email from {sender} ({date_str})\n'
                    f'Subject: {subject}\n\n{chunk}'
                )
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                all_items.append((
                    email_id, mailbox, subject or '', received_at,
                    chunk_index, content, content_hash,
                ))

        # ── Phase 2: bulk-check which hashes already exist ──
        if all_items:
            all_hashes = [item[6] for item in all_items]
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT content_hash FROM claw_code_chunks '
                    'WHERE project_id = %s AND content_hash = ANY(%s)',
                    (EMBED_PROJECT_ID, all_hashes),
                )
                existing_hashes = {row[0] for row in cur.fetchall()}

            new_items = [item for item in all_items if item[6] not in existing_hashes]
            logger.info(
                '%d total chunks, %d already embedded, %d to embed',
                len(all_items), len(all_hashes) - len(new_items), len(new_items),
            )
        else:
            new_items = []

        # ── Phase 3: batch embed all new chunks in one API call ──
        if new_items:
            texts = [item[5] for item in new_items]
            try:
                embeddings = indexer.embed_batch(texts)
            except Exception as exc:
                logger.error('embed_batch failed: %s', exc, exc_info=True)
                # Fall back to per-item embed so partial progress is saved
                embeddings = []
                for text in texts:
                    try:
                        embeddings.append(indexer.embed(text))
                    except Exception as e:
                        logger.error('Single embed failed: %s', e)
                        embeddings.append(None)

            # ── Phase 4: insert all chunks ──
            with conn.cursor() as cur:
                for item, embedding in zip(new_items, embeddings):
                    if embedding is None:
                        errors += 1
                        continue
                    email_id, mailbox, subject, received_at, chunk_index, content, content_hash = item
                    file_path = f'email/{mailbox}/{email_id}/{chunk_index}'
                    cur.execute(
                        """
                        INSERT INTO claw_code_chunks
                            (project_id, file_path, chunk_content, chunk_type,
                             chunk_name, content_hash, embedding, last_modified,
                             subproject_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            EMBED_PROJECT_ID,
                            file_path,
                            content,
                            'email',
                            subject[:200],
                            content_hash,
                            embedding,
                            received_at,
                            mailbox,
                        ),
                    )
                    chunks_written += 1

        # ── Phase 5: mark all emails as embedded (empty + newly done) ──
        processed_email_ids = list({item[0] for item in all_items}) + empty_email_ids
        if processed_email_ids:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE cairn_email_raw SET is_embedded=TRUE WHERE id = ANY(%s)',
                    (processed_email_ids,),
                )

        conn.commit()
        embedded = len(processed_email_ids) + len(empty_email_ids)

    result = {'embedded': embedded, 'errors': errors, 'chunks_written': chunks_written}
    logger.info('embed_email_batch complete: %s', result)
    return result


def get_embed_status() -> dict:
    """Return current embedding progress counts."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE is_embedded = TRUE AND skip_reason IS NULL) AS embedded,
                    COUNT(*) FILTER (WHERE is_embedded = FALSE AND skip_reason IS NULL) AS pending,
                    COUNT(*) FILTER (WHERE skip_reason IS NOT NULL)                    AS skipped,
                    COUNT(*)                                                            AS total
                FROM cairn_email_raw
                """
            )
            embedded, pending, skipped, total = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) FROM claw_code_chunks WHERE project_id=%s AND chunk_type='email'",
                (EMBED_PROJECT_ID,),
            )
            chunk_count = cur.fetchone()[0]

    return {
        'embedded': embedded,
        'pending': pending,
        'skipped': skipped,
        'total': total,
        'vector_chunks': chunk_count,
    }
