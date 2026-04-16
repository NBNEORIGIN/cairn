## DEEK — Cursor Parity And Sovereign Memory Roadmap

This document maps Cursor-style UX/features onto DEEK's current architecture
and records what remains from the original "BM25 + cosine + memory assembler +
skills" proposal.

### What Has Already Landed

- Hybrid retrieval Phase 1:
  - BM25 + pgvector cosine fusion via `HybridRetriever`
  - current `ContextEngine.retrieve_tier2()` contract preserved
  - retrieval mode surfaced in health/status
- Manual model override persistence in the web UI
- Vision-aware routing:
  - image requests avoid DeepSeek
  - explicit Sonnet/Opus overrides stay on Claude-first routing
- Light desktop-style web UI refresh
- Response memory diagnostics:
  - retrieval mode
  - chunk/file counts
  - exact vs semantic hit mix
  - estimated context load
- Watcher-side BM25 cache invalidation after successful reindex
- Smoke / stress harness for product-hardening flows

### What From The Original Memory Prompt Is Still Not Implemented

#### Layer 1 items still deferred

- explicit session/decision weighting inside hybrid retrieval

#### Layer 2 not implemented yet

- memory assembler / context packet object
- provider-specific token budgets
- prompt caching metrics
- cache manager persistence
- provider-specific formatted memory blocks

#### Layer 3 not implemented yet

- disk-backed skill YAMLs
- skill loading and validation
- skill classifier
- skill-scoped retrieval
- skill decision journals
- startup-time trigger embedding cache

### Recommended Implementation Order

#### Phase 2 — Chat UX and operator trust

- richer session replay and transcript restore
- streamed assistant text, not only activity states
- inline patch application / review ergonomics

#### Phase 3 — Memory packet assembly

- add `MemoryPacket` dataclass
- assemble:
  - project rules
  - explicit mentions
  - recent messages
  - hybrid retrieved chunks
- return diagnostics:
  - retrieval mode
  - chunk counts
  - exact vs semantic hit counts
  - estimated budget usage

#### Phase 4 — Skills

- create `projects/*/skills/*/skill.yaml`
- load and validate skill definitions
- map skill -> subproject + key rules
- route retrieval through primary skill scope when matched
- append skill-specific decisions during summarisation

#### Phase 5 — Full Cursor-style agent UX

- streamed assistant text, not just streamed activity events
- inline diff application
- editable chat-generated patches
- tool activity timeline with per-step result summaries
- resumable session detail view
- command palette / settings surface for models, indexing, and rules

### Cursor Feature Mapping

#### Cursor-style chat pane

DEEK should support:

- model selector
- context pills / mentions
- image paste
- chat history
- new chat
- live activity log
- stop generation

Current status:

- implemented: model selector, mentions, image paste, new chat
- partial: history, live activity
- missing: proper stop, streamed text, richer history titles

#### Cursor agent mode

DEEK already has the right backend shape:

- tool loop
- safe/review/destructive risk levels
- approval queue
- WIGGUM outer loop

What is missing is mostly presentation and control:

- clearer step-by-step trace
- pause/stop controls
- better diff review ergonomics
- clearer session replay

#### Cursor codebase indexing

DEEK already differentiates here:

- sovereign storage
- append-only project memory
- hybrid exact + semantic retrieval
- subproject isolation

The next step is to make this visible in the product:

- deepen retrieval source inspection in UI
- make memory diagnostics inspectable
- later add skills so low-reasoning models get tighter context slices

### Why This Matters For The 3090 Upgrade

Once the first RTX 3090 arrives, DEEK's biggest advantage is not just
"local inference", but "local inference with better context discipline".

The combination we want is:

- local or cheap model for routine tasks
- hybrid retrieval for exact domain terms and semantic patterns
- project rules from `core.md`
- eventually skill-scoped memory packets

That is the path that lets smaller local models behave far above their raw
reasoning tier.
