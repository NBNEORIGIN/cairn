"""
Cairn MCP Server
Wraps Cairn FastAPI endpoints as MCP tools for Claude Code and compatible clients.

Specification: CAIRN_MCP_SPEC.md
Start: python mcp/cairn_mcp_server.py
Register: see ~/.claude/mcp_settings.json
"""

import asyncio
import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

CAIRN_BASE_URL = os.environ.get("CAIRN_BASE_URL", "http://localhost:8765")
API_KEY = os.environ.get("CLAW_API_KEY", "claw-dev-key-change-in-production")
HEADERS = {"X-API-Key": API_KEY}

server = Server("cairn")


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    types.Tool(
        name="retrieve_codebase_context",
        description=(
            "Retrieve relevant code chunks from the Cairn codebase index "
            "using hybrid BM25 + semantic search. Use before starting any "
            "development task to surface prior decisions, related code, and "
            "architectural context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language description of what you are looking for. "
                        "Be specific — include function names, file names, or concepts."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": "Project name to scope the search.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of chunks to return. Default 10, max 25.",
                    "default": 10,
                },
                "hybrid": {
                    "type": "boolean",
                    "description": "Use hybrid BM25 + pgvector retrieval. Default true.",
                    "default": True,
                },
            },
            "required": ["query", "project"],
        },
    ),
    types.Tool(
        name="retrieve_chat_history",
        description=(
            "Retrieve relevant development decisions and chat history from "
            "Cairn memory. Use to avoid repeating past mistakes, understand "
            "prior approaches, and maintain continuity across sessions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language description of the decision or topic.",
                },
                "project": {
                    "type": "string",
                    "description": "Project name to scope the search.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of memory entries to return. Default 10.",
                    "default": 10,
                },
                "outcome_filter": {
                    "type": "string",
                    "description": "Filter by outcome: committed, partial, failed, deferred.",
                    "enum": ["committed", "partial", "failed", "deferred"],
                },
            },
            "required": ["query", "project"],
        },
    ),
    types.Tool(
        name="update_memory",
        description=(
            "Write a memory entry to Cairn after completing a task. Required "
            "after every development action that involved a decision, fix, or "
            "discovery. This is how Cairn learns."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project this entry belongs to."},
                "query": {"type": "string", "description": "The original task or question."},
                "decision": {
                    "type": "string",
                    "description": "What was done and why. Include file names, line numbers, reasoning.",
                },
                "rejected": {
                    "type": "string",
                    "description": "What was considered and ruled out.",
                },
                "outcome": {
                    "type": "string",
                    "description": "Result of the task.",
                    "enum": ["committed", "partial", "failed", "deferred"],
                },
                "model": {
                    "type": "string",
                    "description": "Model that performed the primary work.",
                },
                "files_changed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of files modified. Empty array if none.",
                },
            },
            "required": ["project", "query", "decision", "outcome", "model", "files_changed"],
        },
    ),
    types.Tool(
        name="list_projects",
        description=(
            "List all projects currently loaded in Cairn, with status. "
            "Use at session start to confirm which projects are available."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="get_project_status",
        description=(
            "Get the current health and status of Cairn — API, file watcher, "
            "model tiers, and memory. Use at session start to confirm the "
            "system is ready before beginning work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Optional. If provided, returns project-specific stats.",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_business_context",
        description=(
            "Assemble current NBNE business state from module context endpoints "
            "(Manufacture, Ledger, Marketing). Returns make list, financial "
            "position, and marketing pipeline. Gracefully degrades if modules "
            "are offline."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "modules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Modules to query. Options: manufacture, ledger, marketing.",
                    "default": ["manufacture", "ledger", "marketing"],
                },
                "include_recommendations": {
                    "type": "boolean",
                    "description": "Whether to include brain recommendations.",
                    "default": True,
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="cairn_delegate",
        description=(
            "Delegate a one-shot generation, review, extraction, or "
            "classification task to a junior tier (Grok 4 Fast or Claude "
            "Haiku 4.5) via OpenRouter. Use when a task does not require "
            "Sonnet/Opus-tier judgement. Generation routes to Grok 4 Fast; "
            "review/extract/classify route to Haiku 4.5. Every call is "
            "cost-logged to the cairn_delegation_log table. See Rule 1b in "
            "CLAUDE.md for when to prefer this over self-tier execution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "enum": ["generate", "review", "extract", "classify"],
                    "description": (
                        "generate → Grok 4 Fast (code, prose). "
                        "review/extract/classify → Haiku 4.5 (structured JSON)."
                    ),
                },
                "instructions": {
                    "type": "string",
                    "description": "Full prompt for the junior model. Be specific.",
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional prior context. Sent as a separate user "
                        "message before instructions — not as system prompt."
                    ),
                },
                "output_schema": {
                    "type": "object",
                    "description": (
                        "Optional JSON schema. If set, the response is parsed "
                        "and validated; schema_valid:false with raw response "
                        "is returned on failure (no auto-retry)."
                    ),
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max output tokens. Default 4000.",
                    "default": 4000,
                },
                "tier_override": {
                    "type": "string",
                    "enum": ["grok_fast", "haiku"],
                    "description": (
                        "Optional. Force a specific tier regardless of "
                        "task_type. Use sparingly — routing rule exists "
                        "for a reason."
                    ),
                },
                "delegating_session": {
                    "type": "string",
                    "description": (
                        "module + section, e.g. 'beacon:amazon_listings' "
                        "or 'crm:shipment_ingest'. Used for per-module "
                        "spend attribution in the context endpoint."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "One sentence: why this is being delegated instead "
                        "of executed by the caller. Surfaces weak "
                        "delegation choices in the log."
                    ),
                },
            },
            "required": ["task_type", "instructions", "delegating_session", "rationale"],
        },
    ),
    types.Tool(
        name="log_cost",
        description=(
            "Log the cost of every model used in this prompt. Required after "
            "every prompt. Enables cost-benefit analysis of local vs API "
            "models and hardware ROI tracking."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Current session identifier."},
                "prompt_summary": {"type": "string", "description": "One line task description."},
                "project": {"type": "string", "description": "Project this prompt was working on."},
                "costs": {
                    "type": "array",
                    "description": "Cost entry per model used.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "model": {"type": "string"},
                            "tokens_in": {"type": "integer"},
                            "tokens_out": {"type": "integer"},
                            "cost_gbp": {"type": "number"},
                        },
                        "required": ["model", "tokens_in", "tokens_out", "cost_gbp"],
                    },
                },
                "total_cost_gbp": {"type": "number", "description": "Sum of all model costs."},
            },
            "required": ["session_id", "prompt_summary", "project", "costs", "total_cost_gbp"],
        },
    ),
]

# Module context endpoint URLs (for get_business_context)
MODULE_URLS = {
    "manufacture": "http://localhost:8002/api/cairn/context",
    "ledger": "http://localhost:8001/api/cairn/context",
    "marketing": "http://localhost:8004/api/cairn/context",
}


# ── Tool routing ──────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=HEADERS) as client:

            if name == "retrieve_codebase_context":
                params = {
                    "query": arguments["query"],
                    "project": arguments["project"],
                    "limit": arguments.get("limit", 10),
                    "hybrid": arguments.get("hybrid", True),
                }
                r = await client.get(f"{CAIRN_BASE_URL}/retrieve", params=params)
                return [types.TextContent(type="text", text=r.text)]

            elif name == "retrieve_chat_history":
                params = {
                    "query": arguments["query"],
                    "project": arguments["project"],
                    "limit": arguments.get("limit", 10),
                }
                if "outcome_filter" in arguments:
                    params["outcome_filter"] = arguments["outcome_filter"]
                r = await client.get(f"{CAIRN_BASE_URL}/memory/retrieve", params=params)
                return [types.TextContent(type="text", text=r.text)]

            elif name == "update_memory":
                r = await client.post(f"{CAIRN_BASE_URL}/memory/write", json=arguments)
                return [types.TextContent(type="text", text=r.text)]

            elif name == "list_projects":
                r = await client.get(f"{CAIRN_BASE_URL}/projects")
                return [types.TextContent(type="text", text=r.text)]

            elif name == "get_project_status":
                params = {}
                if "project" in arguments:
                    params["project"] = arguments["project"]
                r = await client.get(f"{CAIRN_BASE_URL}/health", params=params)
                return [types.TextContent(type="text", text=r.text)]

            elif name == "get_business_context":
                modules = arguments.get("modules", ["manufacture", "ledger", "marketing"])
                result = {}
                for mod in modules:
                    url = MODULE_URLS.get(mod)
                    if not url:
                        result[mod] = {"status": "unknown_module"}
                        continue
                    try:
                        r = await client.get(
                            url,
                            headers={"Authorization": f"Bearer {API_KEY}"},
                            timeout=2.0,
                        )
                        if r.status_code == 200:
                            result[mod] = r.json()
                        else:
                            result[mod] = {"status": "error", "http_status": r.status_code}
                    except Exception:
                        result[mod] = {"status": "unavailable", "reason": "module not reachable"}
                return [types.TextContent(type="text", text=json.dumps(result))]

            elif name == "log_cost":
                r = await client.post(f"{CAIRN_BASE_URL}/costs/log", json=arguments)
                return [types.TextContent(type="text", text=r.text)]

            elif name == "cairn_delegate":
                # Longer timeout: OpenRouter generation can legitimately take >30s
                # under load, and the client-side 30s cap is applied by the
                # delegation endpoint itself.
                r = await client.post(
                    f"{CAIRN_BASE_URL}/api/delegation/call",
                    json=arguments,
                    timeout=60.0,
                )
                return [types.TextContent(type="text", text=r.text)]

            else:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}),
                )]

    except httpx.ConnectError:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "error": "Cairn API is offline",
                "hint": "Start with: cd D:\\claw && .venv\\Scripts\\python -m uvicorn api.main:app --host 0.0.0.0 --port 8765",
            }),
        )]
    except Exception as exc:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": str(exc)}),
        )]


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
