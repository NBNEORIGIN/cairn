## DEEK — Sovereign Memory System (Implementation-Ready Phase 1)

This document replaces the earlier "Hybrid Retrieval + Memory Assembler + Skills"
prompt for the current DEEK codebase. The earlier draft assumed retrieval,
streaming, and client interfaces that do not exist in this repository yet.

Phase 1 is intentionally narrow and must be fully shippable on today's
architecture before any prompt-assembly or skills work begins.

### Current Architecture Constraints

- `ContextEngine` currently exposes `retrieve_tier2()` and returns plain
  chunk dictionaries.
- `claw_code_chunks` already stores code chunks and archived session chunks in
  pgvector. There is no generic metadata JSON column and no `skill_id` column.
- The model clients do not share a provider-agnostic "pre_assembled messages"
  interface.
- The streaming web path uses SSE GET; image payloads should not depend on a
  giant base64 query string.

### Phase 1 Goal

Implement hybrid retrieval that fits the existing `ContextEngine` contract:

- Keep `ContextEngine.retrieve_tier2()` returning `list[dict]`
- Add BM25 keyword retrieval on top of the existing pgvector cosine search
- Merge BM25 and cosine results with Reciprocal Rank Fusion
- Preserve project and subproject scoping exactly
- Degrade gracefully when `rank-bm25` is unavailable

### Dependencies

Add only:

- `rank-bm25>=0.2.2`

No new npm packages. No schema rewrite. No skill tables.

### Files To Change

1. `core/memory/retriever.py`

Create `HybridRetriever` with:

- BM25 over the existing `claw_code_chunks` corpus for one project scope
- cache key includes both `project_id` and `subproject_id`
- short-lived in-memory cache only; no watcher coupling required in Phase 1
- RRF merge of BM25 + cosine
- output stays compatible with current chunk dicts:
  - `file`
  - `content`
  - `chunk_type`
  - `score`
  - optional `match_quality`
  - optional `bm25_rank`
  - optional `cosine_rank`

2. `core/context/engine.py`

Update `ContextEngine` to:

- initialise `HybridRetriever` when `rank-bm25` is importable and `DATABASE_URL`
  is configured
- add `get_all_chunks(subproject_id=None)` returning existing chunk rows for
  BM25 index construction
- route `retrieve_tier2()` through the hybrid retriever first
- keep existing cosine-only and keyword fallbacks intact
- expose a simple `retrieval_mode` property for health/status reporting

Do not rename `retrieve_tier2()`. Do not introduce a new `ContextChunk` type.

3. `api/main.py`

Expose retrieval status without changing the chat contract:

- `/health` includes:
  - `retrieval_mode`
  - `bm25_available`
- `/status/summary` includes `retrieval_mode` per loaded project

4. `web/src/components/ChatWindow.tsx`

Fix the current message-send bugs while touching the memory work:

- keep the selected manual model until the user changes it
- do not reset `modelOverride` to `auto` after send
- send pasted images through POST `/api/chat`, not SSE GET
- include `image_base64`, `image_media_type`, `model_override`, and
  `subproject_id` in the POST fallback path
- text-only messages may continue using SSE

5. `api/main.py` streaming endpoint

Optional but safe:

- accept `subproject_id`
- accept image params for compatibility

The frontend should still prefer POST for image messages.

### Tests Required In Phase 1

Add focused regression tests for:

- BM25 exact match on token-like terms such as `M-4471`
- hybrid merge boosts chunks found by both BM25 and cosine
- cache key includes `subproject_id`
- `ContextEngine.retrieval_mode` reports `hybrid` when available
- `/health` exposes retrieval diagnostics
- `/chat/stream` still works when optional image params are present

### Explicitly Deferred To Later Phases

Do not implement these in Phase 1:

- provider-specific prompt assembly
- cache-manager token accounting
- skill YAML loading/classification
- skill-scoped retrieval
- new prompt packet formats for Claude/OpenAI/DeepSeek

Those need separate design work after Phase 1 is stable.
