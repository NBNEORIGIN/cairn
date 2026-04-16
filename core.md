# core.md
# Deek (formerly Deek, formerly Claw) — Domain Context
# Read at every session start per CLAUDE.md.
# Canonical source for Deek's architecture, mechanisms, and current state.
# Last updated: 16 April 2026

---

## What Deek Is

Deek is NBNE's sovereign AI brain. It runs on NBNE hardware (currently
`D:\deek\` on the dev box, `/opt/nbne/deek/` on Hetzner — paths change
post-rename).

It is **not** a Cursor or Windsurf replacement. It is a persistent memory
substrate, retrieval engine, model router, and intelligence layer that
sits above every NBNE module.

The shell is the execution layer. Claude Code (or any MCP-compatible
agent) is the intent interpreter. Deek's memory is the accumulating
institutional knowledge — a developer who has memorised every decision,
every dead end, every workaround, and never forgets any of it.

Gates controlled the interface. NBNE controls the memory layer.

---

## What Deek Provides

| Capability | Surface | Consumers |
|---|---|---|
| Hybrid retrieval (BM25 + pgvector) | `GET /retrieve`, MCP `retrieve_codebase_context` | Every CC session |
| Chat history retrieval | `GET /memory/retrieve`, MCP `retrieve_chat_history` | Every CC session |
| Memory write-back | `POST /memory/write`, MCP `update_memory` | Every CC session |
| Wiki search | `GET /api/wiki/search` | Every CC session |
| Wiki compilation | `POST /api/wiki/compile` | Deek itself, manual triggers |
| Cross-tier delegation | `deek_delegate` (becomes `deek_delegate`) | Every CC session |
| Module context aggregation | `GET /api/cairn/context` (becomes `/api/deek/context`) | The business brain |
| Cost logging | `POST /costs/log`, `GET /costs/...` | Every CC session |
| Project status | MCP `list_projects`, `get_project_status` | Every CC session |

---

## The Memory Architecture

### Storage
- **PostgreSQL with pgvector** — `cairn_db` (becomes `deek_db` in
  Phase 5 of rename)
- **Embeddings model** — `nomic-embed-text` (currently); `mxbai-embed-large`
  on `dual_3090` profile

### Retrieval
- **Hybrid BM25 + pgvector** — sparse keyword + dense semantic, combined
  via Reciprocal Rank Fusion
- **Default `limit=5`** per `NBNE_PROTOCOL.md` cost discipline (the wiki
  layer carries structured context, so wider raw retrieval is rarely
  needed)

### Write-back schema
Per `NBNE_PROTOCOL.md` Step 4:
```python
update_memory(
  project=<project>,
  query=<original task>,
  decision=<what was done and why>,
  rejected=<what was considered and ruled out>,
  outcome=<committed|partial|failed|deferred>,
  model=<model that did the primary work>,
  files_changed=[<list of files>],
  delegation_decision=<one sentence: who did the work and why>
)
```

### Indexing cadence
- Per-project reindex via `POST /index?project=<name>` — explicit, not
  automatic
- Triggered by: code change in module, wiki article update, memory
  write-back that adds new searchable content

---

## The Wiki System

### Three scopes
- `wiki/modules/` — one article per module (`manufacture.md`, `phloe.md`,
  etc.) — staff-facing knowledge about each module
- `wiki/patterns/` — reusable patterns (delegation pattern, brief
  refinement loop, etc.)
- `wiki/decisions/` — append-only decision records (D-100, D-101, ...)

### Compile and embed
After editing any wiki article:
```
POST http://localhost:8765/api/wiki/compile?scope=modules
POST http://localhost:8765/api/wiki/compile?scope=patterns
POST http://localhost:8765/api/wiki/compile?scope=decisions
```

Articles are split into chunks, embedded, and indexed for retrieval via
`/api/wiki/search`.

### When to use wiki vs raw retrieval
Wiki articles contain pre-compiled, cross-referenced knowledge. They are
**more useful than raw chunks** for understanding architecture and status.
The `NBNE_PROTOCOL.md` Step 1 prefers wiki search for that reason.

Raw chunks (`retrieve_codebase_context`) are for finding specific code
or comments. Wiki search (`/api/wiki/search`) is for understanding
context.

---

## The Five MCP Tools

These tools are the contract every NBNE CC session depends on. **Do not
change their signatures unilaterally.** Adding new tools is fine;
modifying existing ones is a spanning brief.

### `retrieve_codebase_context`
```
Input:  query (str), project (str), limit (int = 5)
Output: List of code chunks with file paths, scores, snippets
```

### `retrieve_chat_history`
```
Input:  query (str), project (str), limit (int = 5)
Output: List of prior chat memory entries
```

### `update_memory`
```
Input:  project, query, decision, rejected, outcome, model, files_changed,
        delegation_decision
Output: Confirmation of write
```

### `list_projects`
```
Input:  none
Output: All loaded projects with chunk counts
```

### `get_project_status`
```
Input:  project (str)
Output: Health, model availability, memory stats, last index time
```

### Plus delegation tool (not in original spec)
### `deek_delegate` (becomes `deek_delegate`)
```
Input:  task_type ("generate" | "review" | "extract" | "classify"),
        prompt (str),
        context (str, optional),
        output_schema (dict, optional — for review/extract/classify only)
Output: Result from the routed cheaper tier (Grok or Haiku)
```

Routing per `task_type` is in `NBNE_PROTOCOL.md` cost discipline rules.

Full MCP tool specifications live in the MCP server source at
`mcp/deek_mcp_server.py`.

---

## The Breadth Classifier and Decomposition Executor

Deek classifies every incoming task along two axes before dispatching to
a model tier: **domain count** and **coupling**.

### Axis 1 — Domain count
A "domain" is a category of knowledge the task draws on:
- Conversational / natural language
- Code generation (single language, single file)
- Stateful simulation or algorithmic logic
- Rendering or output formatting
- Schema / data modelling
- API contract / integration
- Module-specific business logic

Single-domain tasks are common. Multi-domain tasks are the MoE trap.

### Axis 2 — Coupling
- **Decoupled:** steps can be verified independently
- **Tightly coupled:** correctness only emerges from interaction

### Hardware profile
Deek reads `DEEK_HARDWARE_PROFILE` (becomes `DEEK_HARDWARE_PROFILE`)
from environment. Two values:

- **`dev_desktop`** — single RTX 3050 8GB. Currently installed.
- **`dual_3090`** — 2× RTX 3090, 48GB total. Parts on order.

### Routing matrix

| Breadth / Coupling | dev_desktop | dual_3090 |
|---|---|---|
| Single, conversational | Gemma 4 | Gemma 4 |
| Single, technical (small) | Qwen Coder 7B local | Qwen 72B |
| Single, technical (large) | Claude | Qwen 72B |
| Multi-domain, decoupled | Qwen local, decomposed | Qwen 72B, decomposed |
| Multi-domain, tight | Claude | Claude |
| Long-coherence | Claude | Claude |

On `dev_desktop`, the threshold for escalating to Claude is deliberately
lower — Toby's wall-clock time is more expensive than Claude tokens when
local compute is slow. This inverts on `dual_3090`.

### Classification prompt
Deek runs a preliminary classification call against Gemma 4 (cheap, fast)
before dispatching the real task:

```
Classify the following task.

1. List the distinct knowledge domains it requires (pick from:
   conversational, single-file code, stateful simulation, rendering,
   schema, API contract, module business logic).
2. For each pair of domains, state whether correctness in one can be
   verified independently of the other (decoupled) or not (tight).
3. Estimate whether the task requires long-range coherence across
   many turns or files (yes/no).

Respond with JSON only, no prose:
{
  "domains": [...],
  "coupling": "decoupled" | "tight" | "n/a",
  "long_coherence": true | false,
  "recommended_tier": "gemma" | "qwen-local" | "qwen-decomposed" | "claude"
}

Task:
<the task text>
```

If the classifier returns `qwen-decomposed`, Deek invokes the
decomposition executor.

### Decomposition executor

For multi-domain decoupled tasks:

1. Ask Qwen to produce an ordered list of verifiable sub-steps. Each
   sub-step must be single-domain.
2. For each sub-step in order:
   - Issue the sub-step as a fresh prompt with only the minimal prior
     context needed — not the full running transcript. Avoids KV cache
     contamination.
   - Execute or verify the output.
   - On success: `git commit` with message `deek: step N/M <summary>`.
   - On failure: reset to the last good commit. Retry with a tighter,
     narrower restatement. After 3 failed retries on the same sub-step,
     escalate the remaining work to Claude.
3. When all sub-steps pass, run the full module eval (contract.json,
   behaviour.json) against the assembled result per `DEEK_MODULES.md`.

### Prohibitions
- Deek does not issue cold one-shot multi-domain prompts to Qwen
- Deek does not carry forward a failed Qwen attempt's output as context
  for the retry — reset and narrow
- Deek does not use Gemma 4 for stateful code generation or anything
  requiring algorithmic correctness — Gemma's strength is conversational
  latency, not reasoning depth

### Logging
Every classification decision is logged to the cost log with: task
summary, classifier output, tier chosen, outcome, token spend. This data
will tell us months from now whether the matrix is right or needs
revision.

---

## The WIGGUM Self-Improvement Loop

WIGGUM is Deek's autonomous loop following the Karpathy auto-research
pattern: make a change, measure, keep on improvement, revert on
regression, repeat until interrupted or a target score is reached.

### Loop contract
1. Read the target artefact (`SKILL.md`, prompt, module handler, etc.)
2. Read the associated `evals/<target>.json` assertion file
3. Run the eval harness. Record pass/fail per assertion and aggregate score
4. If score < target: propose one minimal change to the target artefact
5. Re-run the eval harness
6. If new score > previous: `git commit` with message
   `wiggum: +N/M (<change summary>)`. If new score <= previous:
   `git reset --hard HEAD` and try a different change
7. Goto 3

### Autonomy directive
Once started, WIGGUM does not pause to ask whether to continue.
Termination conditions are explicit and only these:
- Perfect score on the eval set for two consecutive iterations
- No score improvement for N consecutive iterations (default `N=10`)
- Token budget exhausted (see Cost Governance below)
- Manual interrupt (SIGINT or `wiggum stop`)

### Cost governance
Loops default to the local model tier appropriate to the current
`DEEK_HARDWARE_PROFILE`:
- On `dev_desktop`: Qwen 2.5 Coder 7B or DeepSeek-Coder-V2 16B locally.
  Slow. Suitable for overnight runs on small eval sets only
- On `dual_3090`: Qwen 2.5 72B or Coder 32B locally. Overnight runs
  against full eval sets become viable

Claude API escalation is permitted only when:
- The target artefact is flagged `tier: claude` in its frontmatter, AND
- A per-run token cap is declared in the invocation, AND
- The run is logged to the cost log with cost attribution

Overnight unattended loops against Claude API are forbidden without an
explicit cap. Default cap: 500k output tokens per target per night. On
`dev_desktop` the cap is tighter (100k).

### Change discipline
Every iteration must be a clean atomic commit. WIGGUM may not:
- Run database migrations during a loop
- Modify files outside the target artefact's directory
- Touch seeded test state
- Cross module boundaries (per `DEEK_MODULES.md`)

If a proposed change would violate these, WIGGUM logs it as out-of-scope
and tries a different change.

### Human review of evals before loop
**Critical safety rule:** WIGGUM only loops against eval sets where every
assertion has been authored or reviewed by a human (`reviewed: true` in
the eval file). Auto-generated assertions are flagged `reviewed: false`
and WIGGUM refuses to run improvement loops against unreviewed sets.
This prevents optimising for a bad rubric overnight.

---

## The Cost Tracking Module

Built into the Deek API — not a separate app.

### What it tracks
Per-prompt cost: model used, tokens in, tokens out, GBP cost, project,
session_id, timestamp. Aggregated by:
- Day, week, month
- Project
- Model
- Session

### Hardware ROI calculation
The cost log directly enables hardware ROI:
```
Monthly API cost without local models = X
Monthly API cost with local models    = Y
Monthly saving                        = X - Y
RTX 3090 cost                         = ~£800 (used)
Payback period                        = £800 / (X - Y) months
```

This calculation updates automatically as the cost log grows. Feeds the
business brain's hardware investment recommendations.

### Surface

```
POST /costs/log                     — log a single prompt
GET  /costs/today                   — today's totals
GET  /costs/month                   — current month + projection
GET  /costs/by-project              — breakdown by project
GET  /costs/by-model                — breakdown by model
GET  /costs/hardware-roi            — ROI calculation
```

Cost data is also written to `data/cost_log.csv` for human-readable
backup that survives DB failures.

---

## The Business Brain

Deek's second goal beyond agentic coding is the NBNE **business brain** —
a system that understands the business deeply enough to reason across all
operations.

### The value chain
**Make → Measure → Sell**
1. Manufacture — what do we make and how many?
2. Ledger — are we making money doing it?
3. Marketing — are we reaching the right people?

### How it works
Each module exposes a context endpoint Deek polls. Cadence and schemas
are in `DEEK_MODULES.md`. Deek assembles responses into a single
business state snapshot, indexes it into pgvector memory, and the brain
reasons over the combined picture.

### Hardware dependency
The brain itself requires the dual RTX 3090 setup (48GB VRAM) for a
72b-class local model to do the cross-chain reasoning at acceptable
speed. **Build the context endpoints now. Run the brain when the
hardware is ready.**

### Example brain output
```json
{
  "date": "2026-03-29",
  "recommendations": [
    {
      "priority": 1,
      "action": "Make 48x SAVILLE silver M2280 on ROLF today",
      "reasoning": "Below stock target, 8.4/day velocity, 41% margin, ROLF available",
      "modules": ["manufacture", "ledger"]
    }
  ],
  "summary": "..."
}
```

---

## Project Registry

Projects Deek currently knows about (via `config.json` per project,
auto-loaded at API start):

| Key | Path | Purpose |
|---|---|---|
| `deek` (was `deek`) | `D:\deek\` | Deek itself |
| `manufacture` (was `manufacturing`) | `D:\manufacture\` | Production app |
| `phloe` | `D:\nbne_business\nbne_platform\` | WaaS booking platform |
| `render` | `D:\render\` | Marketplace publishing |
| `crm` | `D:\crm\` | CRM v2 |
| `ledger` | TBC — greenfield | Financial management |
| `ami` | currently inside Deek | Amazon Intelligence |
| `beacon` | TBC | Google Ads attribution |

**OPEN per LOCAL_CONVENTIONS.md:** project keys still being reconciled
(`manufacture` vs `manufacturing`, etc.). The registry should be the
canonical source of truth — when a project's path or key changes, update
its `config.json` first, restart the API to reload, then propagate to
other systems.

Adding a new project:
1. Create `projects/<key>/config.json` (template: `projects/phloe/config.json`)
2. Create `projects/<key>/core.md` — but per the new architecture, this
   should now reference the module's repo `core.md` rather than duplicate it
3. Restart API to trigger auto-load
4. Verify with `GET /projects`

---

## Shell Frontend (Planned)

When the time is right, build a PowerShell / CMD frontend for Deek that
displays on session start. The interface should feel like a developer
tool, not a chatbot.

### Splash screen design
```
        .
       /|\
      / | \
     /  |  \
    / . | . \
   /   \|/   \
  /     |     \
 /______|______\
   _____|_____
  /     |     \
 /      |      \
/       |       \
|_______|_______|
    ____|____
   /    |    \
  /     |     \
 /______|______\
  ___________
 /           \
/             \
|_____________|

 ██████╗ ███████╗███████╗██╗  ██╗
 ██╔══██╗██╔════╝██╔════╝██║ ██╔╝
 ██║  ██║█████╗  █████╗  █████╔╝
 ██║  ██║██╔══╝  ██╔══╝  ██╔═██╗
 ██████╔╝███████╗███████╗██║  ██╗
 ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝

 Sovereign AI Development System
 North By North East Print & Sign Ltd
 ─────────────────────────────────────
 The brain stays in Northumberland.
```

(The cairn ASCII at the top survives the rename — it's a meaningful
piece of visual heritage for the system, even if the wordmark changes.)

### Followed by
- API status (port 8765 — online/offline)
- Projects loaded with chunk counts
- Active model tier (local/API)
- Memory entries written this session: 0
- A prompt: `> What are we building today?`

### Implementation notes
- PowerShell preferred for Windows compatibility
- Falls back gracefully if Unicode block characters unsupported
- Calls `GET /health` on startup to populate status
- A proper GUI will follow in time — this is the DOS layer, intentionally

---

## API Quick Reference

```
Base URL: http://localhost:8765 (Hetzner: same, internal-only)

GET  /health                          — system status, projects loaded
GET  /retrieve?query=&project=&limit= — hybrid BM25 + pgvector retrieval
POST /memory/write                    — write a memory entry
GET  /memory/retrieve?query=&project= — chat history retrieval
GET  /projects                        — list loaded projects
POST /index?project=                  — trigger manual reindex
GET  /api/wiki/search?q=&top_k=       — wiki article retrieval
POST /api/wiki/compile?scope=         — re-embed wiki articles
GET  /api/cairn/context               — module context aggregation
                                       (becomes /api/deek/context)
POST /costs/log                       — log a prompt's cost
GET  /costs/today                     — today's cost summary
GET  /costs/hardware-roi              — RTX 3090 ROI calculation
POST /costs/price/bulk/               — cost-of-goods lookup (Manufacture
                                       margin engine consumer)
```

---

## What This File Does Not Cover

- **Universal procedure, cost discipline, write-back, hard rules**
  → `NBNE_PROTOCOL.md`
- **Your scope and what you may modify**
  → `CLAUDE.md`
- **SSH, deploy, container names, env vars, Ollama setup, API start
  commands, MCP server start**
  → `INFRASTRUCTURE.md`
- **Paths, project keys, port allocations, naming conventions**
  → `LOCAL_CONVENTIONS.md`
- **Module API contract schemas (Manufacture, Ledger, Marketing context endpoints)**
  → `DEEK_MODULES.md`
- **Detailed MCP server implementation**
  → `DEEK_MCP_SPEC.md` (will be `DEEK_MCP_SPEC.md` post-rename) — TBC
  whether this exists yet

---

## Decision Log

Append-only. Never overwrite. Major architectural decisions affecting
Deek's behaviour or contracts.

### Template
**Date:** YYYY-MM-DD
**ID:** D-NNN
**Title:** <short title>
**Context:** <what prompted this>
**Decision:** <what was decided>
**Rationale:** <why>
**Rejected:** <alternatives ruled out>

---

## The Deek Principle

Every prompt: **retrieve first, delegate appropriately, write back after.**

The procedure is the memory. The memory is the product. The brain stays
in Northumberland.

---

*End of document. Updates require a date in the header and a new
Decision Log entry if architectural.*
