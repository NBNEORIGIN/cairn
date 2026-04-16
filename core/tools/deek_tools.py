"""
Deek federation + memory tools for the chat agent.

These tools read from the Cairn database — specifically the claw_code_chunks
table — rather than from the filesystem or external HTTP endpoints. They give
the chat agent direct access to:

  - Live module snapshots (chunk_type='module_snapshot'), refreshed every 15
    minutes by api/routes/deek_federation.snapshot_poll_loop from each
    module's /api/cairn/snapshot endpoint.
  - Ingested email corpus (chunk_type='email'), written by
    scripts/process_deek_inbox.py every 15 minutes via host cron.
  - Compiled wiki articles (chunk_type='wiki'), maintained by the wiki
    freshness loop in api/main.py.

Why these tools exist:

  Before today, the chat agent could only:
    (a) ripgrep the project filesystem via search_code, or
    (b) HTTP-fetch module context endpoints via web_fetch, which fails
        from inside the deek-api container because localhost:<module_port>
        doesn't resolve to the host.

  The existing search_code tool walks wiki/*.md as files and so picks up
  wiki content lexically — but never sees emails (which live only in
  the DB) or live module snapshots (also DB-only). The chat was reporting
  "Manufacturing: connection refused / Email: not a module I have" even
  though the data was sitting one SQL query away.

  These tools close the gap.
"""
from __future__ import annotations

import os
from typing import Any

from .registry import Tool, RiskLevel


# ── Connection helper ──────────────────────────────────────────────────────


def _get_conn():
    """Open a psycopg2 connection to the Deek database.

    Uses DATABASE_URL from env. pgvector registration is best-effort —
    the tools in this module don't require it (they query on text
    columns only) but we register if available so downstream callers
    that select `embedding` don't break.
    """
    import psycopg2

    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg2.connect(dsn, connect_timeout=5)
    try:
        from pgvector.psycopg2 import register_vector

        register_vector(conn)
    except Exception:
        pass
    return conn


def _embed(query: str) -> list[float] | None:
    """Get an embedding for a query string, or None if no provider available."""
    try:
        from core.wiki.embeddings import get_embed_fn

        fn = get_embed_fn()
        if not fn:
            return None
        return fn(query[:2000])
    except Exception:
        return None


# ── Tool 1: get_module_snapshot ────────────────────────────────────────────


def _get_module_snapshot(
    project_root: str,
    module: str | None = None,
    **kwargs,
) -> str:
    """
    Return the most recent federated snapshot markdown for a named module.

    If module is omitted (or empty), returns an index of every module
    that currently has a snapshot, with the timestamp of each. This lets
    the chat discover what modules are available before drilling in.
    """
    try:
        conn = _get_conn()
    except Exception as exc:
        return f"DB unreachable: {exc}"

    try:
        with conn.cursor() as cur:
            if not module:
                cur.execute(
                    """SELECT file_path, indexed_at, LENGTH(chunk_content)
                       FROM claw_code_chunks
                       WHERE project_id = 'deek'
                         AND chunk_type = 'module_snapshot'
                       ORDER BY indexed_at DESC"""
                )
                rows = cur.fetchall()
                if not rows:
                    return (
                        "No module snapshots are currently ingested. "
                        "Register a module in deploy/modules.json and restart "
                        "deek-api, or POST /api/cairn/poll-modules."
                    )
                lines = ["Registered modules with snapshots:"]
                for path, indexed_at, size in rows:
                    # file_path is "snapshots/{module}.md"
                    name = path.split("/")[-1].rsplit(".", 1)[0]
                    lines.append(
                        f"  - {name}: {size} bytes, last refreshed "
                        f"{indexed_at.isoformat() if indexed_at else 'unknown'}"
                    )
                lines.append(
                    "\nCall get_module_snapshot(module=<name>) to read a specific one."
                )
                return "\n".join(lines)

            # Normalise — handle both "manufacture" and "snapshots/manufacture.md"
            name = module.strip().lower()
            if name.startswith("snapshots/"):
                name = name.split("/", 1)[1]
            if name.endswith(".md"):
                name = name[:-3]

            cur.execute(
                """SELECT chunk_content, indexed_at
                   FROM claw_code_chunks
                   WHERE project_id = 'deek'
                     AND chunk_type = 'module_snapshot'
                     AND file_path = %s""",
                (f"snapshots/{name}.md",),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """SELECT file_path FROM claw_code_chunks
                       WHERE project_id = 'deek' AND chunk_type = 'module_snapshot'"""
                )
                available = [r[0].split("/")[-1].rsplit(".", 1)[0] for r in cur.fetchall()]
                hint = (
                    f" Available: {', '.join(available)}." if available
                    else " No modules have snapshots yet."
                )
                return f"No snapshot for module '{name}'.{hint}"

            content, indexed_at = row
            age = ""
            if indexed_at:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc).replace(tzinfo=None)
                delta = now - indexed_at
                mins = int(delta.total_seconds() // 60)
                age = f"\n\n_(snapshot age: {mins} minutes)_"
            return f"{content}{age}"
    finally:
        conn.close()


get_module_snapshot_tool = Tool(
    name="get_module_snapshot",
    description=(
        "Fetch the most recent live state snapshot for an NBNE business "
        "module (Manufacture, CRM, Ledger, Render, Beacon, etc.) from the "
        "Deek federation layer. Snapshots are refreshed automatically every "
        "15 minutes by polling each module's /api/cairn/snapshot endpoint "
        "and storing the markdown in claw_code_chunks (chunk_type="
        "'module_snapshot'). "
        "Use this whenever the user asks about live operational state — "
        "'what is manufacture doing', 'how's the FBA pipeline', 'what's in "
        "CRM pipeline', etc. "
        "Call without a module name to list what's available. "
        "This tool always returns the most recent data; do NOT try to fetch "
        "module URLs directly via web_fetch — that fails from inside the "
        "container because localhost doesn't resolve to the host."
    ),
    risk_level=RiskLevel.SAFE,
    fn=_get_module_snapshot,
    required_permission="get_module_snapshot",
)


# ── Tool 2: search_emails ──────────────────────────────────────────────────


def _search_emails(
    project_root: str,
    query: str,
    limit: int = 5,
    **kwargs,
) -> str:
    """
    Semantic + lexical search over the ingested cairn@ inbox.

    Combines semantic match (via pgvector cosine distance on embedding)
    with a lexical LIKE fallback on the subject/body for exact-name
    queries like sender lookups.
    """
    try:
        limit = int(limit)
    except Exception:
        limit = 5
    limit = max(1, min(limit, 20))

    try:
        conn = _get_conn()
    except Exception as exc:
        return f"DB unreachable: {exc}"

    try:
        results: list[tuple[float, str, str, str]] = []
        with conn.cursor() as cur:
            # Semantic leg — only runs if we can embed the query
            embedding = _embed(query)
            if embedding is not None:
                try:
                    cur.execute(
                        """SELECT file_path, chunk_name,
                                  LEFT(chunk_content, 400),
                                  embedding <=> %s::vector AS distance
                           FROM claw_code_chunks
                           WHERE project_id = 'deek'
                             AND chunk_type = 'email'
                             AND embedding IS NOT NULL
                           ORDER BY embedding <=> %s::vector
                           LIMIT %s""",
                        (embedding, embedding, limit),
                    )
                    for path, name, snippet, dist in cur.fetchall():
                        # Score = 1 - cosine distance; higher is better
                        score = 1.0 - float(dist)
                        results.append((score, path, name or "(no subject)", snippet))
                except Exception:
                    pass  # fall through to lexical leg

            # Lexical leg — useful for sender-name / exact-phrase queries
            try:
                cur.execute(
                    """SELECT file_path, chunk_name, LEFT(chunk_content, 400)
                       FROM claw_code_chunks
                       WHERE project_id = 'deek'
                         AND chunk_type = 'email'
                         AND (chunk_content ILIKE %s OR chunk_name ILIKE %s)
                       ORDER BY indexed_at DESC
                       LIMIT %s""",
                    (f"%{query}%", f"%{query}%", limit),
                )
                for path, name, snippet in cur.fetchall():
                    # Lexical hits get a fixed score just below top semantic matches
                    results.append((0.5, path, name or "(no subject)", snippet))
            except Exception:
                pass

        if not results:
            return f"No emails found matching: {query}"

        # Dedupe by file_path, keep highest score
        by_path: dict[str, tuple[float, str, str]] = {}
        for score, path, name, snippet in results:
            if path not in by_path or by_path[path][0] < score:
                by_path[path] = (score, name, snippet)

        ranked = sorted(
            by_path.items(),
            key=lambda kv: kv[1][0],
            reverse=True,
        )[:limit]

        lines = [f"Top {len(ranked)} email results for: {query}", ""]
        for path, (score, name, snippet) in ranked:
            lines.append(f"[{score:.2f}] {name}")
            lines.append(f"  id: {path}")
            compact = " ".join(snippet.split())
            if len(compact) > 300:
                compact = compact[:300] + "..."
            lines.append(f"  {compact}")
            lines.append("")
        return "\n".join(lines).rstrip()
    finally:
        conn.close()


search_emails_tool = Tool(
    name="search_emails",
    description=(
        "Search the cairn@nbnesigns.com inbox for messages matching a "
        "query. Runs a hybrid semantic + lexical search against the "
        "email chunks stored in claw_code_chunks (chunk_type='email'). "
        "Use this when the user asks about a sender, a topic, a recent "
        "enquiry, or anything that might have been emailed rather than "
        "documented in the wiki. Arguments: query (free text), "
        "limit (default 5, max 20). "
        "Emails are refreshed automatically every 15 minutes from the "
        "cairn@ IMAP inbox."
    ),
    risk_level=RiskLevel.SAFE,
    fn=_search_emails,
    required_permission="search_emails",
)


# ── Tool 3: search_wiki ────────────────────────────────────────────────────


def _search_wiki(
    project_root: str,
    query: str,
    limit: int = 5,
    **kwargs,
) -> str:
    """
    Semantic + lexical search over compiled wiki articles.

    Prefers pgvector semantic ranking when an embedder is available,
    falls back to ILIKE matching when it isn't (e.g. on a fresh tenant
    without an Ollama/OpenAI embedding provider).
    """
    try:
        limit = int(limit)
    except Exception:
        limit = 5
    limit = max(1, min(limit, 20))

    try:
        conn = _get_conn()
    except Exception as exc:
        return f"DB unreachable: {exc}"

    try:
        rows_out: list[tuple[float, str, str, str]] = []
        with conn.cursor() as cur:
            embedding = _embed(query)
            if embedding is not None:
                try:
                    cur.execute(
                        """SELECT file_path, chunk_name,
                                  LEFT(chunk_content, 600),
                                  embedding <=> %s::vector AS distance
                           FROM claw_code_chunks
                           WHERE project_id = 'deek'
                             AND chunk_type = 'wiki'
                             AND embedding IS NOT NULL
                           ORDER BY embedding <=> %s::vector
                           LIMIT %s""",
                        (embedding, embedding, limit),
                    )
                    for path, name, snippet, dist in cur.fetchall():
                        score = 1.0 - float(dist)
                        rows_out.append((score, path, name or path, snippet))
                except Exception:
                    pass

            if not rows_out:
                cur.execute(
                    """SELECT file_path, chunk_name, LEFT(chunk_content, 600)
                       FROM claw_code_chunks
                       WHERE project_id = 'deek'
                         AND chunk_type = 'wiki'
                         AND (chunk_content ILIKE %s OR chunk_name ILIKE %s)
                       ORDER BY indexed_at DESC
                       LIMIT %s""",
                    (f"%{query}%", f"%{query}%", limit),
                )
                for path, name, snippet in cur.fetchall():
                    rows_out.append((0.5, path, name or path, snippet))

        if not rows_out:
            return f"No wiki articles found matching: {query}"

        lines = [f"Top {len(rows_out)} wiki results for: {query}", ""]
        for score, path, name, snippet in rows_out[:limit]:
            lines.append(f"[{score:.2f}] {name}")
            lines.append(f"  path: {path}")
            compact = " ".join(snippet.split())
            if len(compact) > 500:
                compact = compact[:500] + "..."
            lines.append(f"  {compact}")
            lines.append("")
        return "\n".join(lines).rstrip()
    finally:
        conn.close()


search_wiki_tool = Tool(
    name="search_wiki",
    description=(
        "Search the NBNE wiki knowledge base — process SOPs, decision "
        "logs, supplier notes, module documentation, incident reports. "
        "Runs a hybrid semantic + lexical search over the "
        "chunk_type='wiki' rows in claw_code_chunks. "
        "Use this for 'how do we handle X', 'what's our process for Y', "
        "'what did we decide about Z' questions. "
        "Arguments: query (free text), limit (default 5, max 20). "
        "The wiki has ~300 articles covering every major area of the "
        "business — prefer this over search_code for process/policy "
        "questions, which ripgreps raw files and misses semantic matches."
    ),
    risk_level=RiskLevel.SAFE,
    fn=_search_wiki,
    required_permission="search_wiki",
)
