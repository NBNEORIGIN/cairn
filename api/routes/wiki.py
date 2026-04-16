"""
Wiki Layer API routes.

Mounted at /api/wiki/* in the Deek FastAPI app.

Provides:
  GET  /api/wiki/search?q=&top_k=   — hybrid search with wiki boost
  GET  /api/wiki/graph               — graph.json for the visual map
  GET  /api/wiki/article/{path:path} — single wiki article as markdown
  POST /api/wiki/compile?scope=      — trigger compilation job
  GET  /api/wiki/status              — compilation status and article counts
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wiki", tags=["Wiki"])

_CLAW_ROOT = Path(__file__).resolve().parents[2]
_WIKI_ROOT = _CLAW_ROOT / 'wiki'


@router.get("/search")
async def wiki_search(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(5, ge=1, le=20, description="Max results"),
    project: str = Query("deek", description="Project scope"),
):
    """Semantic wiki search via pgvector cosine similarity.

    Embeds the query using the same provider as wiki compilation
    (Ollama -> OpenAI -> DeepSeek), then does cosine similarity
    against wiki chunks in pgvector. Falls back to keyword search
    on disk files if embedding or DB is unavailable.
    """
    import os

    db_url = os.getenv('DATABASE_URL', '')

    # Try semantic search first
    if db_url:
        try:
            from core.wiki.embeddings import get_embed_fn
            embed_fn = get_embed_fn()

            if embed_fn:
                import psycopg2
                from pgvector.psycopg2 import register_vector

                query_embedding = embed_fn(q[:2000])
                conn = psycopg2.connect(db_url, connect_timeout=5)
                register_vector(conn)

                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT file_path, chunk_content, chunk_name,
                               1 - (embedding <=> %s::vector) AS score
                        FROM claw_code_chunks
                        WHERE project_id = %s
                          AND chunk_type = 'wiki'
                          AND embedding IS NOT NULL
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                    """, (query_embedding, project, query_embedding, top_k))
                    rows = cur.fetchall()
                conn.close()

                if rows:
                    articles = [{
                        "path": row[0],
                        "content": row[1],
                        "name": row[2],
                        "score": round(float(row[3]), 3),
                    } for row in rows]
                    return {"articles": articles, "total": len(articles), "method": "semantic"}
        except Exception as exc:
            logger.warning("Semantic wiki search failed: %s", exc)

    # Fall back to keyword search on disk files
    articles = _search_wiki_files(q, top_k)
    return {"articles": articles, "total": len(articles), "method": "keyword"}


def _search_wiki_files(query: str, top_k: int) -> list[dict]:
    """Fallback: search wiki markdown files on disk when DB has no wiki chunks."""
    results = []
    query_lower = query.lower()
    terms = query_lower.split()

    for md_file in _WIKI_ROOT.rglob('*.md'):
        try:
            content = md_file.read_text(encoding='utf-8')
            content_lower = content.lower()
            score = sum(1 for term in terms if term in content_lower)
            if score > 0:
                rel_path = str(md_file.relative_to(_CLAW_ROOT)).replace('\\', '/')
                results.append({
                    "path": rel_path,
                    "content": content,
                    "name": md_file.stem,
                    "_score": score,
                })
        except Exception:
            pass

    results.sort(key=lambda r: r["_score"], reverse=True)
    for r in results:
        r.pop("_score", None)
    return results[:top_k]


@router.get("/graph")
async def wiki_graph():
    """Return graph.json for the visual map component."""
    graph_path = _WIKI_ROOT / 'modules' / 'graph.json'
    if not graph_path.exists():
        raise HTTPException(404, "graph.json not found")

    return json.loads(graph_path.read_text(encoding='utf-8'))


@router.get("/article/{path:path}")
async def wiki_article(path: str):
    """Return a single wiki article as markdown.

    Path is relative to wiki/ and may omit the .md extension.
    Example: /api/wiki/article/modules/phloe
    """
    # Normalise path
    if not path.endswith('.md'):
        path = f'{path}.md'

    article_path = _WIKI_ROOT / path
    # Security: prevent path traversal
    try:
        article_path = article_path.resolve()
        wiki_resolved = _WIKI_ROOT.resolve()
        if not str(article_path).startswith(str(wiki_resolved)):
            raise HTTPException(403, "Path traversal not allowed")
    except Exception:
        raise HTTPException(403, "Invalid path")

    if not article_path.exists():
        raise HTTPException(404, f"Article not found: {path}")

    content = article_path.read_text(encoding='utf-8')
    return {
        "path": path,
        "content": content,
        "name": article_path.stem,
        "last_modified": datetime.fromtimestamp(
            article_path.stat().st_mtime
        ).isoformat(),
    }


@router.post("/compile")
async def wiki_compile(
    scope: str = Query("all", description="Compilation scope: all|modules|products|clients"),
):
    """Trigger wiki compilation job.

    Scope controls which article types are compiled:
      - all: everything
      - modules: module articles only (uses Sonnet)
      - products: product articles only (uses DeepSeek)
      - clients: client articles only (uses OpenRouter)
    """
    from core.wiki.compiler import WikiCompiler

    compiler = WikiCompiler()
    try:
        result = await compiler.compile(scope=scope)
        return result
    except Exception as exc:
        logger.error("Wiki compilation failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Compilation failed: {exc}")


@router.get("/status")
async def wiki_status():
    """Return wiki compilation status, article counts, and health."""
    meta_path = _WIKI_ROOT / '_meta' / 'last_compiled.json'
    log_path = _WIKI_ROOT / '_meta' / 'compilation_log.json'

    last_compiled = {}
    if meta_path.exists():
        try:
            last_compiled = json.loads(meta_path.read_text(encoding='utf-8'))
        except Exception:
            pass

    recent_logs = []
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text(encoding='utf-8'))
            recent_logs = logs[-5:] if isinstance(logs, list) else []
        except Exception:
            pass

    # Count articles by category
    counts = {}
    for category_dir in _WIKI_ROOT.iterdir():
        if category_dir.is_dir() and not category_dir.name.startswith('_'):
            md_count = len(list(category_dir.glob('*.md')))
            if md_count > 0:
                counts[category_dir.name] = md_count

    return {
        "wiki_root": str(_WIKI_ROOT),
        "article_counts": counts,
        "total_articles": sum(counts.values()),
        "last_compiled": last_compiled,
        "recent_compilations": recent_logs,
    }
