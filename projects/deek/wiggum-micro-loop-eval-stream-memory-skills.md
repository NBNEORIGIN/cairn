# DEEK — WIGGUM Micro Loop Prompt: Eval, Streaming, Memory, Skills

Use this prompt for the next DEEK hardening milestone.

This run must implement the following five items in a way that fits the
current DEEK architecture. Do not rewrite the request path around a new
provider abstraction. Work with the existing `DeekAgent`, `ContextEngine`,
and web SSE flow.

## Goal

Make DEEK measurably better at:

1. answering core prompts consistently
2. showing the answer as it forms
3. failing fast instead of hanging
4. assembling context more intelligently for the chosen provider
5. loading domain-specific skills from disk without a large classifier system

## Scope

Implement all of the following.

### 1. Evaluation suite for 10 core prompts

- Add a disk-backed prompt suite for DEEK under `projects/deek/`.
- Include 10 prompts that exercise:
  - architecture explanation
  - model routing
  - context retrieval
  - validation behavior
  - streaming path
  - session memory
  - tool approval behavior
  - subproject scoping
  - image routing
  - WIGGUM/self-test understanding
- Each prompt must define:
  - prompt text
  - required markers / concepts
  - optional forbidden markers
- Add a script that:
  - calls the local DEEK API
  - runs the suite
  - scores each answer
  - writes a compact cache/result file for the status page

### 2. Stream partial assistant text

- Keep the existing SSE activity log.
- Add partial assistant text events so the response pane can show a live draft.
- Fit this into the current non-streaming model clients.
- Do not block on full provider-native token streaming.
- The web UI should display:
  - live draft text
  - live activity log
  - final message on `complete`

### 3. Stronger timeout and stop handling

- Keep the existing model-call timeout/fallback behavior.
- Add a request-level deadline for the full chat operation.
- On deadline expiry:
  - return a useful timeout/fallback answer
  - never leave the UI hanging indefinitely
- Preserve cooperative `/chat/stop`.
- Stop requests should clear live draft state in the UI.

### 4. Memory assembler phase 1

- Add a lightweight `MemoryAssembler` that fits the current architecture.
- Do not replace `ContextEngine.retrieve_tier2()` or the current tool loop.
- The assembler should:
  - work with the existing prompt sections
  - apply provider-aware token budgets
  - trim retrieved context sensibly
  - optionally inject compact recent-history excerpts
  - optionally inject skill context blocks
- Expose budget metadata back to the UI.

### 5. Skills phase 1

- Add disk-backed skills under `projects/*/skills/*/skill.yaml`.
- Use manual activation only in this phase.
- No embedding classifier yet.
- A minimal phase-1 skill system must support:
  - loading skills from disk
  - exposing available skills for a project
  - manual activation per message
  - optional skill-bound subproject defaults
  - injecting skill rules/context into assembled memory
  - appending archived-session bullets to `decisions.md` for active skills

## Constraints

- No speculative rewrite of the model clients.
- No new npm packages.
- No pgvector schema rewrite.
- Keep current `ContextEngine.build_context_prompt()` behavior compatible.
- Keep current `MessageEnvelope` / `AgentResponse` contracts compatible.
- Skills must degrade gracefully when no YAML files exist.

## Success Criteria

- `projects/deek/chat-request-flow-golden-answer.md` remains a valid reference.
- A 10-prompt evaluator script runs locally and produces a pass/fail summary.
- The chat pane shows partial assistant text before the final `complete`.
- Requests time out cleanly instead of hanging for minutes.
- Context assembly reports provider budget usage in metadata.
- Manual skill activation works end-to-end.
- Archived sessions append bullets to active skill `decisions.md` files.
- `pytest` focused regressions pass.
- `python scripts/smoke_product_hardening.py` passes.
- `cd web && npm run build` passes.

## Delivery

After implementation:

1. Run the prompt smoke/eval script.
2. Run focused backend regressions.
3. Run the smoke script.
4. Run the web build.
5. Report:
   - files changed
   - eval result
   - pytest result
   - smoke result
   - build result
   - deferred follow-up items
