# CLAW Chat Request Flow — Golden Answer

Use this as the reference answer for the prompt:

`Read the CLAW codebase and explain how chat requests flow from the web UI to the model response. Name the main files involved and point out where model routing, context retrieval, validation, and streaming happen.`

## End-to-End Flow

### 1. Web UI entry points

The browser-side chat experience lives in [web/src/components/ChatWindow.tsx](D:/claw/web/src/components/ChatWindow.tsx).

- Normal text messages prefer SSE and open an `EventSource` to the Next.js proxy at `/api/chat/stream`.
- Image messages and non-stream fallbacks use `fetch('/api/chat', ...)`.
- The browser does **not** usually call FastAPI directly. It goes through Next.js proxy routes first.

The proxy routes are:

- [web/src/app/api/chat/route.ts](D:/claw/web/src/app/api/chat/route.ts)
  This forwards POST requests to FastAPI `/chat` and adds the API key header.
- [web/src/app/api/chat/stream/route.ts](D:/claw/web/src/app/api/chat/stream/route.ts)
  This forwards SSE requests to FastAPI `/chat/stream` and streams the body back to the browser.

### 2. FastAPI request handling

The main backend entry points are in [api/main.py](D:/claw/api/main.py).

- `POST /chat`:
  - validates the request with `ChatRequest`
  - checks auth with `verify_api_key`
  - creates a `MessageEnvelope`
  - calls `agent.process(envelope)`
  - serialises the returned `AgentResponse` to JSON
- `GET /chat/stream`:
  - parses query params into a `MessageEnvelope`
  - calls `agent.process_streaming(envelope)`
  - wraps yielded events into `text/event-stream`
- `POST /chat/stop`:
  - marks the session for cooperative cancellation

The envelope shape is defined in [core/channels/envelope.py](D:/claw/core/channels/envelope.py).

### 3. Agent orchestration

The main orchestration happens in [core/agent.py](D:/claw/core/agent.py).

`ClawAgent.process()` does the non-streaming flow:

1. clears any old stop flag for the session
2. writes the user message into SQLite via `MemoryStore`
3. handles tool-approval responses if present
4. resolves `@` mentions through `ContextEngine.resolve_mentions()`
5. builds the context prompt through `ContextEngine.build_context_prompt()`
6. estimates token load and calls `route_decision(...)`
7. selects tool exposure through `_get_tools_for_task(...)`
8. chooses the client via `_get_api_client(...)` or Ollama
9. calls the model through `_chat_with_fallback(...)`
10. runs the SAFE-tool loop through `_run_tool_loop(...)` if a safe tool is returned
11. validates the final answer through `_validate_final_response(...)`
12. stores the assistant message and returns `AgentResponse`

`ClawAgent.process_streaming()` follows the same logic but yields SSE events like:

- `status`
- `routing`
- `tokens`
- `tool_start`
- `tool_end`
- `tool_queued`
- `complete`
- `error`
- `done`

### 4. Context retrieval

Context retrieval is implemented in [core/context/engine.py](D:/claw/core/context/engine.py).

The main method is `build_context_prompt(...)`, which assembles:

- Tier 1:
  project `core.md`, always included
- Tier 2:
  retrieved code/context chunks from `retrieve_tier2(...)`
- Tier 3:
  full-file loads only when the agent explicitly calls `read_file`

Current retrieval is:

- `hybrid` when the BM25 + cosine retriever is available
- `cosine` when pgvector retrieval is available but hybrid is not
- `keyword` fallback otherwise

The engine prefers the hybrid retriever first, then falls back to embedding search, then keyword search.

### 5. Model routing

Routing is implemented in [core/models/router.py](D:/claw/core/models/router.py).

The current entry point is `route_decision(...)`, not just `route()`.

It uses:

- the task classifier from [core/models/task_classifier.py](D:/claw/core/models/task_classifier.py)
- project config overrides like `force_model`
- per-message `force_tier` derived from `model_override`
- project rules such as `CLAW_TIER4_PROJECTS`
- context size and local-model availability

The result is a `RoutingDecision` containing:

- provider choice
- desired tier
- actual tier
- whether Opus is required
- explanation / rule metadata

### 6. Model clients and fallback

The provider clients are:

- [core/models/claude_client.py](D:/claw/core/models/claude_client.py)
- [core/models/deepseek_client.py](D:/claw/core/models/deepseek_client.py)
- [core/models/openai_client.py](D:/claw/core/models/openai_client.py)
- [core/models/ollama_client.py](D:/claw/core/models/ollama_client.py)

`_chat_with_fallback(...)` in [core/agent.py](D:/claw/core/agent.py) wraps provider calls, applies a hard timeout, and falls back on retryable failures or timeouts.

### 7. Validation

Post-response validation lives in [core/models/output_validator.py](D:/claw/core/models/output_validator.py).

The validator checks:

- tool-description without actual tool execution
- refusal
- hallucinated file paths
- phloe tenant-isolation issues
- empty response
- Python syntax on written files

The important point is that validation is not just passive logging.
`_validate_final_response(...)` in [core/agent.py](D:/claw/core/agent.py) can:

- accept the answer
- retry with a corrected prompt
- recover using another provider
- synthesize a fallback summary from tool results

### 8. Streaming

Streaming is split across frontend and backend:

- frontend SSE consumer:
  [web/src/components/ChatWindow.tsx](D:/claw/web/src/components/ChatWindow.tsx)
- Next.js SSE proxy:
  [web/src/app/api/chat/stream/route.ts](D:/claw/web/src/app/api/chat/stream/route.ts)
- FastAPI stream endpoint:
  [api/main.py](D:/claw/api/main.py)
- streaming generator:
  [core/agent.py](D:/claw/core/agent.py)

The browser listens for agent activity events and renders status/progress before the final `complete` event.

## Short Summary

The real flow is:

`ChatWindow.tsx`
→ Next.js chat proxy or SSE proxy
→ `api/main.py`
→ `MessageEnvelope`
→ `ClawAgent.process()` / `process_streaming()`
→ `ContextEngine.build_context_prompt()`
→ `route_decision(...)`
→ provider client via `_chat_with_fallback(...)`
→ SAFE tool loop when needed
→ `_validate_final_response(...)`
→ JSON or SSE response back to the UI

## Pass Criteria For This Prompt

A good CLAW answer to the prompt should:

- name the Next.js proxy layer, not just FastAPI
- mention `MessageEnvelope`
- mention `core/agent.py`
- mention `core/context/engine.py`
- mention `core/models/router.py`
- mention `core/models/output_validator.py`
- mention `process_streaming()`
- describe validation as active recovery, not just metadata logging
