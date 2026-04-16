# DEEK — WIGGUM Micro Loop Prompt: Product Hardening Pass

Use this prompt for the current UX and operator-trust milestone.

This micro loop is intentionally narrower than the long-range memory roadmap.
Do not attempt the full skills system, prompt caching, or provider-specific
memory packet assembly in this run. Those remain separate architecture phases.

## Goal

Turn DEEK from a developer-shell prototype into a trustworthy desktop-style app
for day-to-day use, while hardening the retrieval/runtime path enough that
smaller local models can benefit from better context discipline when the first
RTX 3090 arrives.

## Scope

Implement all of the following in one cohesive pass:

1. Light Windows-style UI refresh
   - Move the web UI to a light, desktop-app look.
   - Replace terminal-like dark surfaces with paneled cards, soft elevation,
     clearer controls, and a readable workspace layout.
   - Preserve all existing functionality: model picker, image paste, mentions,
     activity feed, stop, approvals, history, and session loading.

2. Memory diagnostics in the response pane
   - Expose retrieval diagnostics to the user in a human-friendly format.
   - Include:
     - retrieval mode
     - retrieved chunk count
     - distinct file count
     - exact / semantic / exact+semantic hit counts
     - pinned mention count
     - estimated context token load
     - approximate context budget percentage
   - Show diagnostics inline in the chat UI, not only in logs.

3. BM25 cache invalidation on reindex
   - When a watched file is reindexed successfully, invalidate the BM25 cache
     for that project so hybrid retrieval reflects the updated corpus.
   - Wire watcher lifecycle into app startup when codebase path and DB are
     available, but fail soft if the watcher or DB is unavailable.

4. Smoke / stress verification
   - Add a small repeatable smoke script for:
     - `/health`
     - `/status/summary`
     - `/chat`
     - `/chat/stream`
     - `/chat/stop`
   - Mock model calls so the script is deterministic and does not spend API
     credits.
   - Include a short repeated-request stress pass to catch regressions in
     session handling and metadata payload shape.

## Constraints

- No new npm packages.
- No speculative architecture rewrites.
- Keep the current `ContextEngine.retrieve_tier2()` contract intact.
- Keep the current tool loop behavior intact.
- Any watcher startup must degrade gracefully when prerequisites are missing.
- Verification must include `pytest -q` and `npm run build`.

## Success Criteria

- The web UI looks like a light Windows app rather than a terminal.
- Assistant messages show inspectable memory diagnostics.
- Hybrid retrieval caches are invalidated after successful file reindex.
- A smoke script runs without external API calls and reports success.
- `pytest -q` passes.
- `cd web && npm run build` passes.

## Delivery

After implementation:

1. Run the smoke script.
2. Run the full backend test suite.
3. Run the web production build.
4. Report:
   - files changed
   - smoke result
   - pytest result
   - build result
   - any remaining deferred features for later phases
