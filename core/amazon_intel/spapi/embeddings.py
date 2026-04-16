"""
Listing content embeddings via pgvector.

Generates embeddings for listing text fields (title, bullets, description, combined)
using the shared embedding provider (nomic-embed-text via Ollama, or OpenAI fallback).
Stores in ami_listing_embeddings with change detection via text hashing.

768-dim vectors matching the existing Deek pgvector schema.
"""
import hashlib
import json
import logging
from typing import Callable

from core.amazon_intel.db import get_conn

logger = logging.getLogger(__name__)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _build_texts(row: dict) -> dict[str, str]:
    """Build text strings for each embedding field type from a listing content row."""
    title = row.get('title') or ''
    bullets = []
    for i in range(1, 6):
        b = row.get(f'bullet{i}')
        if b:
            bullets.append(b)
    bullet_text = '\n'.join(bullets)
    description = row.get('description') or ''

    texts = {}
    if title:
        texts['title'] = title
    if bullet_text:
        texts['bullets'] = bullet_text
    if description:
        texts['description'] = description

    # Combined: title + bullets + description for holistic similarity
    combined_parts = [p for p in [title, bullet_text, description] if p]
    if combined_parts:
        texts['combined'] = '\n\n'.join(combined_parts)

    return texts


def embed_listing(asin: str, marketplace: str, embed_fn: Callable[[str], list[float]]) -> dict:
    """
    Embed listing content for a single ASIN. Skips if text hasn't changed.
    Returns {'embedded': int, 'skipped': int, 'fields': [...]}
    """
    # Fetch current listing content
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT title, bullet1, bullet2, bullet3, bullet4, bullet5, description
                   FROM ami_listing_content WHERE asin = %s AND marketplace = %s""",
                (asin, marketplace),
            )
            row_data = cur.fetchone()

    if not row_data:
        return {'embedded': 0, 'skipped': 0, 'error': 'no listing content'}

    cols = ['title', 'bullet1', 'bullet2', 'bullet3', 'bullet4', 'bullet5', 'description']
    row = dict(zip(cols, row_data))
    texts = _build_texts(row)

    if not texts:
        return {'embedded': 0, 'skipped': 0, 'error': 'no text to embed'}

    # Check existing hashes
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT field_type, text_hash FROM ami_listing_embeddings WHERE asin = %s AND marketplace = %s",
                (asin, marketplace),
            )
            existing = {r[0]: r[1] for r in cur.fetchall()}

    embedded = 0
    skipped = 0
    fields = []

    for field_type, text in texts.items():
        text_h = _text_hash(text)
        if existing.get(field_type) == text_h:
            skipped += 1
            continue

        try:
            vector = embed_fn(text[:8000])
            if not vector or len(vector) != 768:
                logger.warning("Bad embedding for %s/%s/%s: len=%s", asin, marketplace, field_type,
                               len(vector) if vector else 0)
                continue

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ami_listing_embeddings (asin, marketplace, field_type, embedding, text_hash)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (asin, marketplace, field_type) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            text_hash = EXCLUDED.text_hash,
                            created_at = NOW()
                    """, (asin, marketplace, field_type, json.dumps(vector), text_h))
                    conn.commit()

            embedded += 1
            fields.append(field_type)
        except Exception as e:
            logger.error("Embedding failed for %s/%s/%s: %s", asin, marketplace, field_type, str(e)[:200])

    return {'embedded': embedded, 'skipped': skipped, 'fields': fields}


def embed_all_listings(marketplace: str = 'UK', batch_size: int = 100) -> dict:
    """
    Embed all listing content for a marketplace. Skips unchanged listings.
    Returns summary.
    """
    from core.wiki.embeddings import get_embed_fn

    embed_fn = get_embed_fn()
    if not embed_fn:
        return {'error': 'no embedding provider available', 'embedded': 0}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT asin FROM ami_listing_content WHERE marketplace = %s",
                (marketplace,),
            )
            asins = [r[0] for r in cur.fetchall()]

    total_embedded = 0
    total_skipped = 0
    errors = 0

    for i, asin in enumerate(asins):
        try:
            result = embed_listing(asin, marketplace, embed_fn)
            total_embedded += result.get('embedded', 0)
            total_skipped += result.get('skipped', 0)
        except Exception as e:
            logger.error("Embedding batch error at %s: %s", asin, str(e)[:200])
            errors += 1

        if (i + 1) % 100 == 0:
            logger.info("Embedding progress: %d/%d ASINs (marketplace=%s)", i + 1, len(asins), marketplace)

    return {
        'marketplace': marketplace,
        'total_asins': len(asins),
        'total_embedded': total_embedded,
        'total_skipped': total_skipped,
        'errors': errors,
    }


def semantic_search(query: str, marketplace: str = 'UK', field_type: str = 'combined',
                    limit: int = 20) -> list[dict]:
    """
    Semantic search over listing embeddings.
    Returns matching ASINs with similarity scores.
    """
    from core.wiki.embeddings import get_embed_fn

    embed_fn = get_embed_fn()
    if not embed_fn:
        return []

    query_vec = embed_fn(query[:8000])
    if not query_vec or len(query_vec) != 768:
        return []

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT le.asin, le.marketplace,
                       1 - (le.embedding <=> %s::vector) AS similarity,
                       lc.title, lc.brand, lc.image_count
                FROM ami_listing_embeddings le
                JOIN ami_listing_content lc ON le.asin = lc.asin AND le.marketplace = lc.marketplace
                WHERE le.marketplace = %s AND le.field_type = %s
                ORDER BY le.embedding <=> %s::vector
                LIMIT %s
            """, (json.dumps(query_vec), marketplace, field_type, json.dumps(query_vec), limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
