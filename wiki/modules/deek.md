# Deek

## What It Does
NBNE's sovereign AI development memory system. Runs on NBNE hardware and replaces
cloud-based coding assistants. Deek remembers every decision, dead end, and
workaround across all projects. It also serves as the business brain — assembling
live data from all modules into a unified context that staff can query in plain
English.

## Who Uses It
- **Toby Fletcher** — business queries, project direction, the "boardroom scenario"
- **Claude Code** — principal developer, uses Deek's memory on every task
- **Qwen / DeepSeek** — junior developers, delegated mechanical tasks
- **Staff** — web dashboard for business questions

## Tech Stack
- Backend: FastAPI + PostgreSQL (pgvector) on nbne1 (192.168.1.228)
- Frontend: Next.js (web-business, deek.nbnesigns.co.uk)
- Retrieval: Hybrid BM25 + pgvector cosine similarity with RRF fusion
- Embeddings: nomic-embed-text (768-dim)
- Session storage: SQLite per project
- Hosting: Hetzner (178.104.1.152, port 8765) + local development (D:\deek)
- MCP: deek_mcp_server.py exposes 5 tools to Claude Code

## Connections
- **Feeds data to:** All modules (memory retrieval, context assembly)
- **Receives data from:** [[modules/phloe]] (context), [[modules/manufacture]] (context),
  [[modules/ledger]] (context), [[modules/amazon-intelligence]] (context),
  [[modules/etsy-intelligence]] (context), [[modules/crm]] (semantic search)
- **Context endpoint:** Deek IS the context layer — it queries all other modules

## Current Status
- Build phase: Production (API, web UI, MCP server, wiki layer)
- Last significant change: Wiki layer implementation (April 2026)
- Known issues: RTX 1050 limits local inference; RTX 3090 arriving for upgrade
- Indexing: Active for all registered projects (pgvector + nomic-embed-text)

## Key Concepts
- **3-tier context:** Tier 1 (core.md), Tier 2 (hybrid BM25+pgvector), Tier 3 (on-demand file reads)
- **Memory write-back:** Every non-trivial task writes decisions back to Deek
- **Delegation protocol:** Tasks classified by complexity → assigned to appropriate model tier
- **Business brain:** Assembles live data from all modules for natural language queries
- **Wiki layer:** Compiled knowledge articles with retrieval boost over raw chunks
- **Make → Measure → Sell:** The NBNE value chain that Deek's modules map to

## Related
- [[modules/phloe]] — largest module, most active development
- [[modules/manufacture]] — production data feeds business brain
- [[modules/amazon-intelligence]] — listing health in dashboard
- [[modules/etsy-intelligence]] — Etsy sales data in dashboard
