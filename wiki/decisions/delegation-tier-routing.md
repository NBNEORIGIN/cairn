# Decision Record — cairn_delegate Tier Routing

**Status:** Ratified, deployed, dogfooded (D-103, 2026-04-15).

**Scope:** The cross-module delegation tool `cairn_delegate`, its routing
rule, its surface shape, its sovereignty posture, and follow-on operational
decisions.

**Audience:** Future sessions deciding whether `cairn_delegate` should be
extended, reshaped, or replaced.

---

## Design decisions (D-A through D-F)

### D-A — New package under `core/delegation/`, not `claw/delegation/`

**Decided:** business logic lives at `D:\claw\core\delegation\*`.

**Rejected:** top-level `D:\claw\delegation\` per the brief's original
wording. Cairn's convention is that `D:\claw\core\<domain>\*` holds
business logic and the repo root holds entry-points and config. Placing
delegation logic at the root would invent a new convention for a concern
that is not structurally new.

**Reasoning:** consistency with `core/models/`, `core/memory/`,
`core/social/`, `core/wiki/`. Documented in
`docs/cairn/LOCAL_CONVENTIONS.md`.

### D-B — HTTPS REST only, no MCP wrapper at launch

**Decided:** `cairn_delegate` is exposed as
`POST https://cairn.nbnesigns.co.uk/api/delegation/call` with
`X-API-Key: $CLAW_API_KEY`. No MCP tool declaration in
`mcp/cairn_mcp_server.py`.

**Rejected:** adding a `types.Tool` entry + dispatch branch for
`cairn_delegate` at launch. The MCP server is already live with 7 tools;
one more is a trivial change. But every module session (Beacon, Phloe,
Render, CRM) calls Cairn over HTTPS anyway — those sessions have no MCP
channel to Cairn. The MCP wrapper would only benefit CC sessions working
directly on `D:\claw`, which is the minority case.

**Reasoning:** minimum-surface. The REST endpoint serves every caller.
Adding MCP is a one-tool-entry change if demand emerges. Closed for
current scope.

### D-C — Routing rule: `task_type` → model

**Decided:** deterministic routing with optional override.

- `task_type="generate"` → `x-ai/grok-4-fast`
- `task_type="review" | "extract" | "classify"` → `anthropic/claude-haiku-4.5`
- `tier_override` ∈ `{"grok_fast", "haiku"}` wins unconditionally.

**Rejected:** automatic escalation on failure. If Grok fails a generate
call, Cairn does NOT retry on Haiku. The caller (usually Sonnet) decides
whether to accept with tweaks (Outcome B), rewrite itself (Outcome C), or
retry at a different tier explicitly. Silent escalation would hide the
failure from the cost log and mask spec ambiguity.

**Rejected:** per-task quality-based routing ("if instructions contain
'review', use Haiku"). Ambiguous and hides the routing decision from the
caller.

**Reasoning:** D-103 shows the realistic output from Grok is 90%-correct
with 1–2 contract bugs. That is handled by the caller, not by retry
machinery. Determinism makes cost and outcome predictable.

### D-D — Sovereignty via OpenRouter, existing accepted trust boundary

**Decided:** use OpenRouter as the provider for both Grok Fast and Haiku
4.5. No new trust boundary added.

**Rejected:** direct xAI API, direct Anthropic API. Both would require
separate API keys, separate cost tracking, separate retry/timeout code.
OpenRouter is already used by `core/social/drafter.py`,
`core/wiki/compiler.py`, and the internal `core/models/router.py` fallback.

**Claim made:** inputs and outputs are not fed back into training.
- OpenRouter ToS §5: provider-deferred; OR's own training use is opt-in
  default-off.
- xAI Enterprise ToS: "xAI shall not use any User Content for any of its
  internal AI or other training purposes." Auto-deletion at 30 days.
  De-identified aggregates may persist — named explicitly.
- Anthropic API: generally excludes API traffic from training.

**Claim NOT made:** nothing leaves the UK. Both tiers route through US/UK
infrastructure. The wiki article (`wiki/patterns/delegation.md`) states
this explicitly.

**Verification pending:** xAI ToS exact wording. `x.ai/legal/*` is
Cloudflare-gated against automated WebFetch; current quotation is
WebSearch-sourced (2026-04-15). Toby to confirm against the live page.

### D-E — Project key for memory write-backs: `"claw"` not `"cairn"`

**Decided:** all `update_memory` / retrieval calls related to this work
use `project="claw"`.

**Rejected:** registering a new `"cairn"` project. The Cairn API already
reports a phantom `"cairn"` entry in `/projects` (no config, not ready).
Splitting the codebase memory across two project keys would halve
retrieval quality for no benefit.

**Reasoning:** `claw` is the codebase, Cairn is the ecosystem brand.
Documented in `docs/cairn/LOCAL_CONVENTIONS.md`.

### D-F — Cost log table separate from existing `cost_log`

**Decided:** create new `cairn_delegation_log` table with call-level grain
(one row per `cairn_delegate` invocation).

**Rejected:** reusing the existing `cost_log` table / CSV. That log is
prompt-level — one row per prompt with a list of per-model costs.
Different grain makes cross-aggregation error-prone.

**Rejected:** writing to the SQLite `conversations` table with a
`[cost-log]` content prefix (how `/costs/log` currently piggybacks).
Structured querying over a content-prefix hack is fragile.

**Reasoning:** call-level grain is required for the `/api/cairn/context`
aggregations: per-module spend, per-model spend, schema-failure rate,
MTD/YTD windows. The existing `log_cost` tool stays unchanged; the new
table writes alongside.

---

## Operational decisions (D-101 through D-103)

### D-101 — Code layout: `core/delegation/`

**Decided:** files placed under `D:\claw\core\delegation\`:

- `openrouter_client.py` — thin httpx wrapper for chat-completions.
- `router.py` — `task_type` → model routing (NOT `core/models/router.py`).
- `cost.py` — pricing table, USD→GBP conversion, cost computation.
- `log.py` — `cairn_delegation_log` table writer.
- `context.py` — aggregate helpers for `/api/cairn/context`.

**Rejected:** reusing `core/models/openai_client.py`. It's a full multi-turn
agent client with tool-calling, history, image support — overkill for a
one-shot delegation. Thin httpx wrapper per the brief's §0 step 4.

**Rejected:** extending `core/models/router.py`. That router governs Cairn's
internal agent orchestration (Ollama / DeepSeek / Claude / OpenRouter
fallback). `cairn_delegate` is a different concern: external CC sessions
delegating IN to Cairn, not Cairn's own model selection.

**Route handler:** `/api/delegation/call` handler in `api/main.py`.
Matched existing FastAPI convention — Cairn keeps route handlers inline
unless the module is large enough to warrant `api/routers/*.py` split.

### D-102 — Public nginx exposure of `/api/delegation/` only

**Decided:** Hetzner nginx block on
`cairn.nbnesigns.co.uk` proxies `/api/delegation/` to `localhost:8765`.
Change mirrored in repo at
`deploy/nginx/cairn-business.conf.snippet` for reviewability and
reprovisioning recovery.

**Rejected (Option 2):** also expose `/ami/*`. No current cross-module
need; speculative.

**Rejected (Option 3):** separate `api.cairn.nbnesigns.co.uk` subdomain.
Speculative refactor, no scope justification.

**Rejected:** exposing `/api/cairn/context` publicly. No external caller
has asked for aggregates; minimum-surface principle holds. Re-evaluate
when a real caller appears.

**Verification:** `POST https://cairn.nbnesigns.co.uk/api/delegation/call`
returns 401 without `X-API-Key`, 422 with valid key + empty body.

### D-103 — Routing recommendation after first dogfooding

**Decided:** keep `generate → x-ai/grok-4-fast` as the default. Do NOT
pass `output_schema` on generate calls. Senior-tier review is the quality
gate, not schema validation.

**Evidence:** dogfooded by Opus 4.6 on 2026-04-15 to generate
`core/delegation/context.py` — an SQLite aggregation helper with a
detailed spec. Grok Fast call: 26 seconds, 1829 in / 4946 out, £0.0022.

**What worked:** overall structure, stdlib-only constraint, path
resolution, `sqlite_master` guard, `COALESCE` on all SUMs, parameterised
queries, MTD/YTD boundary math.

**What broke (caught in Sonnet review, fixed under 3 minutes):**

- Module-derivation: `session.split('/', 1)` on a slash-less string
  returns `[session]`, not `[]`. The code set `module = parts[0]` → the
  full session string instead of the spec's required `'unknown'`. A
  contract bug, not a shape bug. No schema validator would catch it.
- Numeric type drift: `round(0, 4)` returns `int`; spec required `float`.
  Fixed via `round(float(...), 4)` coercion.

**Outcome category:** B (accepted with tweaks). Fix extracted to
`_module_for()` helper in `core/delegation/context.py`.

**Cost delta:** ~£0.05 saved vs estimated self-execution. Small in
absolute terms. The meaningful win is operational — Sonnet's attention
freed from mechanical work.

**Pattern for future module sessions:** cheap tier writes narrow-scope
function from a detailed spec, Sonnet reviews, Sonnet accepts / tweaks /
rewrites. Not multi-file refactors. Not cross-module design.

---

## Phase 2 candidates (not in current scope)

- **MCP wrapper for `cairn_delegate`.** One-tool-entry change in
  `mcp/cairn_mcp_server.py` if CC sessions working directly on `D:\claw`
  need it.
- **Public `/api/cairn/context` route.** Add a second nginx location
  block on `cairn-business.conf` when a real external caller needs
  aggregates. Deferred per minimum-surface.
- **Automatic tier escalation on `outcome != "success"`.** Currently the
  caller handles failure. Automation would hide failures from cost log.
  Reconsider if D-103 pattern no longer holds after N more dogfooding
  runs.
- **Per-project pricing caps.** Currently rate-limited by OpenRouter
  account-level credit cap. Fine while total delegation spend is under
  £1/month; revisit if a single module drives outsized use.

---

## References

- `wiki/patterns/delegation.md` — the pattern article every future
  session should read before calling the tool.
- `projects/claw/core.md` — D-103 in full, the empirical record.
- `docs/cairn/HANDOVER_2026-04-15_CAIRN_DELEGATE.md` — pre-build
  recon and amendments that shaped the decisions above.
- `docs/cairn/LOCAL_CONVENTIONS.md` — `CLAW_API_KEY`, project naming,
  code layout.
- `CLAUDE.md` STEP 2b Rule 1b — the enforcement rule that points at
  this pattern.
