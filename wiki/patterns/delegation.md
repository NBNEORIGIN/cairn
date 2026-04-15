# Delegation via cairn_delegate

## What it does

`cairn_delegate` is a Cairn API tool that lets any module session push a small,
well-bounded piece of work to a cheaper model tier (Grok Fast or Claude Haiku
4.5) via OpenRouter, and get back the output plus token and cost accounting.
It is exposed as `POST https://cairn.nbnesigns.co.uk/api/delegation/call`,
authenticated by `X-API-Key: $CLAW_API_KEY`. Every call is logged to the
`cairn_delegation_log` SQLite table on the Cairn host and surfaced via the
Cairn context endpoint. Returns: `{ output, model_used, tokens_in, tokens_out,
cost_gbp, outcome, schema_valid, duration_ms }`.

## When to use it

- You're writing a helper function, SQL query, or CRUD handler from a
  detailed, self-contained specification that fits in under ~500 words.
- You need a structured review verdict on a small diff or proposed code
  change, where the output is a JSON object with a fixed shape.
- You need to extract structured data from prose — form fields from a brief,
  enum values from a support email, entities from a decision log.
- You need to classify a short input against a fixed set of labels
  (severity, component, task type, tier).
- The output is cheap for you to read and review in full. If you cannot
  review it, do not delegate it.

## When NOT to use it

- Architectural decisions, cross-module design, or anything that requires
  holding invariants across more than two files. These need Sonnet or Opus
  judgement at call time, not review after the fact.
- Code with subtle correctness requirements. Per D-103, Grok missed two
  stated edge cases (slash-less module derivation, int-vs-float type drift)
  on a task with a careful specification. The junior tier reliably produces
  happy-path code and reliably misses 1–2 contract details per task.
- Work you cannot review line by line. Delegation without review is just
  degraded execution at a lower price.
- Anything that would route to a tier you would not have used directly.
  Qwen 7B locally is free and handles most mechanical single-file edits; do
  not pay OpenRouter for work the local model already does well.
- Code generation that depends on context Grok does not have (unexposed
  module internals, private conventions, project-specific utilities). Sonnet
  writing it directly is cheaper once you count the rework.

## The two tiers and what each is good for

### Grok Fast (`x-ai/grok-4-fast`)

- Pricing: $0.20 per 1M input, $0.50 per 1M output. At USD/GBP 0.79: roughly
  £0.00016 per 1K input, £0.0004 per 1K output.
- Routed to on `task_type="generate"` unless `tier_override` says otherwise.
- Strengths: fast, cheap, produces well-structured Python / SQL / shell /
  small JSON from a careful prompt. Follows stylistic instructions well
  (stdlib-only, `from __future__ import annotations`, naming conventions).
- Weaknesses: misses stated edge cases. Default-drifts numeric types. Will
  produce a syntactically correct answer to an under-specified prompt rather
  than ask for clarification. Do not pass an `output_schema` on generate
  calls (per D-103); let the prompt carry the spec and the caller review the
  output on content, not shape.

### Claude Haiku 4.5 (`anthropic/claude-haiku-4.5`)

- Pricing: $1.00 per 1M input, $5.00 per 1M output. At USD/GBP 0.79: roughly
  £0.0008 per 1K input, £0.004 per 1K output. ~5–10× Grok.
- Routed to on `task_type="review"`, `"extract"`, or `"classify"`.
- Strengths: follows JSON schemas reliably. Produces richer review verdicts
  than Grok when given a small diff plus acceptance criteria. Better at
  refusing to answer when the input is malformed, rather than hallucinating.
- Weaknesses: more expensive; only worth it when the output IS structured
  data the caller will machine-consume, or when nuance in prose matters
  (code review, risk analysis, disambiguation).

## How to call it

```bash
curl -X POST https://cairn.nbnesigns.co.uk/api/delegation/call \
  -H "X-API-Key: $CLAW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "generate",
    "instructions": "Write a Python function that ...",
    "delegating_session": "module-session-id-or-name",
    "rationale": "one sentence: why Grok is the right tier for this"
  }'
```

Required fields: `task_type`, `instructions`, `delegating_session`,
`rationale`. Optional: `tier_override` (`"grok_fast" | "haiku"`),
`output_schema` (permissive JSON schema — only pass on review/extract/classify,
never on generate), `max_tokens`, `timeout_ms`.

`CLAW_API_KEY` lives in `D:\claw\.env` for local use and in the Hetzner host
environment for production. It is not `CAIRN_API_KEY` — see
`docs/cairn/LOCAL_CONVENTIONS.md` for the canonical env var name.

Response shape (success):

```json
{
  "output": "...",
  "model_used": "x-ai/grok-4-fast",
  "tokens_in": 1829,
  "tokens_out": 4946,
  "cost_gbp": 0.0022,
  "outcome": "success",
  "schema_valid": null,
  "duration_ms": 26000
}
```

`outcome` is one of: `success`, `schema_failure`, `api_error`, `refusal`,
`timeout`. Any outcome other than `success` means the caller does the work
itself, with the failure as context.

## Concrete examples

### Example 1: delegating CRUD endpoint generation

Task: add `GET /api/invoices/<id>` to the Ledger FastAPI app. The pattern
already exists elsewhere in the same file; Grok just needs to mirror it.

```json
{
  "task_type": "generate",
  "delegating_session": "ledger-session-2026-04-15",
  "rationale": "Mirror existing GET /api/invoices/ pattern, 40 LOC helper plus route handler",
  "instructions": "In the style of ledger/api/routes/invoices.py lines 48-92, add a handler for GET /api/invoices/{invoice_id} that returns 404 if the invoice is missing, 200 with the invoice JSON otherwise. Use the same Pydantic response model as the list endpoint. Return diff format."
}
```

What could go wrong: Grok might invent a different response model or skip
the 404 case. Caller reviews the diff before applying. ~£0.002 per call.

### Example 2: delegating code review with structured output

Task: review a 30-line diff against three acceptance criteria. Haiku returns
a JSON verdict the caller can machine-consume.

```json
{
  "task_type": "review",
  "delegating_session": "beacon-phase2-review",
  "rationale": "Short diff, fixed verdict shape, Haiku's schema-following is the right tier",
  "instructions": "Given this diff (...) and these three acceptance criteria (...), return a verdict.",
  "output_schema": {
    "type": "object",
    "properties": {
      "verdict":             {"type": "string", "enum": ["approve", "reject", "request_changes"]},
      "criteria_met":        {"type": "array", "items": {"type": "string"}},
      "criteria_missed":     {"type": "array", "items": {"type": "string"}},
      "suggested_changes":   {"type": "array", "items": {"type": "string"}}
    },
    "required": ["verdict", "criteria_met", "criteria_missed"]
  }
}
```

What could go wrong: Haiku refuses on a malformed diff — caller gets
`outcome: "refusal"` and handles it. Stricter schemas constrain Haiku's
richness; prefer permissive over strict when you have a choice.

### Example 3: delegating documentation drafting

Task: draft a module README section from a spec the caller has already
written. No code correctness risk; the caller reviews the prose.

```json
{
  "task_type": "generate",
  "delegating_session": "manufacture-docs-2026-04-15",
  "rationale": "Prose draft from a bulleted spec, Sonnet-quality not required for first pass",
  "instructions": "Given this bullet list (...) write a 3-paragraph README section in the style of wiki/modules/manufacture.md. No placeholders."
}
```

What could go wrong: Grok's tone may drift from the house style; caller
edits before committing. Acceptable — this is draft material, not final.

### Example 4: anti-example — do NOT delegate this

Task: decide whether Cairn's memory retrieval should use RRF or weighted
sum fusion when combining BM25 and pgvector results.

This is a cross-module architectural decision. It affects every project's
retrieval quality. The cost of getting it wrong is weeks of degraded memory
recall. Sonnet (or Opus) thinks through the trade-offs directly; Grok
delegation would produce a plausible-sounding wrong answer at a fraction of
the token cost, and the reviewer (Sonnet) would still have to do the full
analysis to know whether to accept it. Delegation here saves nothing and
loses context-depth. Self-execute.

## Sovereignty position

Cairn's code and memory stay on NBNE hardware. OpenRouter is an existing
accepted external relationship (already used by `core/social/drafter.py`,
`core/wiki/compiler.py`, and the internal model router). `cairn_delegate`
adds no new trust boundary — it exercises the existing one.

The practical claim the project makes is "inputs and outputs are not fed
back into model training," not "nothing leaves the UK." Both Grok Fast and
Haiku 4.5 route through US/UK infrastructure via OpenRouter. Relevant ToS
points, verified 2026-04-15:

- **OpenRouter Privacy Policy**
  (<https://openrouter.ai/privacy>): "We do not control, and are not
  responsible for, LLMs' handling of your Inputs or Outputs, including for
  use in their model training." OpenRouter defers training-data handling
  to the provider.
- **OpenRouter ToS §5**
  (<https://openrouter.ai/terms>): OpenRouter's own training-use of user
  content is opt-in via account settings — default is off. Private
  input/output logging is also user-enabled, default off.
- **xAI Enterprise ToS**
  (<https://x.ai/legal/terms-of-service-enterprise>): "xAI shall not use
  any User Content for any of its internal AI or other training purposes."
  Content auto-deletes within 30 days unless flagged. A Zero Data Retention
  option exists. xAI MAY create and use de-identified aggregates for
  product development — a carve-out worth naming.
  **Verification pending — Toby to confirm exact wording. xAI's legal pages
  are Cloudflare-gated against automated fetches; the current quotation is
  sourced via WebSearch (2026-04-15), not direct WebFetch. The URL is the
  authoritative reference for humans.**
- **Anthropic (via OpenRouter)**: Anthropic's API policy generally
  excludes API traffic from training. Haiku via OpenRouter inherits this
  through OpenRouter's provider-deferred posture.

OpenRouter calls xAI as the intermediary customer, which means the
Enterprise ToS applies to this relationship — not the consumer-grade terms
bound to Grok chat on X. That distinction matters; do not conflate them.

What this does NOT claim: no data crosses the Atlantic, nothing is logged
anywhere, or that anonymised aggregates cannot be built from de-identified
content. Those are stronger claims the evidence does not support.

## Cost log: how to read it

Every call writes one row to `cairn_delegation_log` in the claw SQLite DB
(`CLAW_DATA_DIR/claw.db`, default `data/claw.db`). Schema:

```sql
CREATE TABLE cairn_delegation_log (
    id                  TEXT PRIMARY KEY,
    called_at           TEXT NOT NULL,
    delegating_session  TEXT NOT NULL,
    rationale           TEXT,
    task_type           TEXT NOT NULL,
    model_used          TEXT NOT NULL,
    tokens_in           INTEGER NOT NULL DEFAULT 0,
    tokens_out          INTEGER NOT NULL DEFAULT 0,
    cost_gbp            REAL NOT NULL DEFAULT 0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    schema_valid        INTEGER,
    outcome             TEXT NOT NULL,
    output_excerpt      TEXT
);
```

The Cairn context endpoint surfaces aggregates (per-module spend, per-model
totals, schema failure rate, MTD/YTD windows) via `GET /api/cairn/context`.
Note: that endpoint is currently Hetzner-loopback only — it is NOT exposed
via nginx, per the minimum-surface principle in D-102. If you need
aggregates from outside the host, either SSH to the host and query
`sqlite3 data/claw.db` directly, or request a public route and justify the
caller.

Sample query — delegation spend in the current month:

```sql
SELECT
    substr(delegating_session, 1, instr(delegating_session || '/', '/') - 1) AS module,
    COUNT(*) AS calls,
    ROUND(SUM(cost_gbp), 4) AS gbp
FROM cairn_delegation_log
WHERE called_at >= strftime('%Y-%m-01', 'now')
GROUP BY module
ORDER BY gbp DESC;
```

Module derivation splits on `/` — sessions without a slash aggregate under
`'unknown'`. That behaviour is the D-103 fix; see the helper `_module_for`
in `core/delegation/context.py`.

## What to do when junior tier produces unacceptable output

Per D-103, three realistic outcomes exist after a junior-tier generation:

**Outcome A — accepted as-is.** Rare. The code compiles, passes review,
meets every acceptance criterion. Commit, log, move on.

**Outcome B — accepted with tweaks.** The common case on any task more
complex than boilerplate. The junior tier gets the structure right and
misses 1–2 contract details. Senior tier (Sonnet/Opus) fixes them in under
5 minutes. This is the pattern D-103 recorded: Grok produced 90%-correct
code, Sonnet caught a slash-less edge case and a numeric type coercion
bug, total tweak time <3 minutes. Commit the reviewed version, not the raw
junior output.

**Outcome C — rejected and rewritten.** The junior output is
fundamentally wrong: misread the spec, invented an API that does not
exist, produced plausible but incorrect SQL. Rewrite at the senior tier
with the failure as context ("Grok produced X; here is why X is wrong; do
it properly"). The cost of the failed junior call is not lost — it usually
surfaces an ambiguity in the spec that the senior tier now addresses.

Implicit in all three: delegation cost is `junior generation + senior
review`, not `junior generation` alone. The headline cost delta from D-103
(£0.0022 junior vs roughly £0.05 self-execution) is real but small in
absolute terms. The main win is operational — the senior tier's attention
is freed from mechanical work to judge content.

## Schema design guidance

Per D-103 and the prior T2 finding (session 5):

- **Generate tasks**: do NOT pass `output_schema`. The deliverable is
  source code, prose, or a SQL statement — schema validation adds nothing
  and constrains Grok's ability to produce well-structured output. The
  caller reviews on content, not shape.
- **Review / extract / classify tasks**: DO pass `output_schema`, and
  prefer permissive over strict. Haiku follows schemas reliably; strict
  schemas constrain richness on review tasks where the value is in the
  prose of the verdict, not the enum of it.
- **Required vs optional fields**: mark only what you will actually check
  as required. Optional fields the caller reads defensively cost nothing
  if absent; required fields the model cannot produce cause
  `outcome: "schema_failure"` and waste a call.
- **Enums**: use them where the output IS one of a small closed set
  (verdict, severity, tier). Do not enumerate free-text fields.

## Lessons from initial dogfooding (D-103)

D-103 is the only empirical observation of `cairn_delegate` in production
as of 2026-04-15. The verbatim findings below are preserved rather than
summarised — they are the evidence the rest of this article rests on.

> **Outcome category:** B (accepted with tweaks).
>
> **Time from first delegation call to integrated, deployed code:** ~12
> minutes end-to-end (Grok call 26s + Sonnet review ~3 min + tweak /
> integrate / test / commit / deploy ~9 min).
>
> **Cost:** 1 cairn_delegate call (plus one £0.00 ping for connectivity;
> no retries). Total OpenRouter spend £0.0022 (1829 in / 4946 out via Grok
> Fast). Estimated cost if Sonnet had written this directly: roughly
> £0.05–£0.10. Net delta: saved roughly £0.05. Not the headline number;
> the headline is that the tool demonstrably works for a real production
> change.
>
> **What was right:** overall structure, imports, stdlib-only constraint
> honoured. Correct default path resolution. Table-existence guard via
> `sqlite_master`. `COALESCE(SUM(cost_gbp), 0)` on every SUM. Ordering on
> aggregations exactly matches spec. Parameterised queries throughout.
> MTD/YTD boundary math via `datetime.replace(...)` is correct.
>
> **What was wrong:**
>
> - Module-derivation bug. `session.split('/', 1)` on a slash-less string
>   returns `[session]`, not `[]`. Code set `module = parts[0]` → the
>   full session string, not `'unknown'` as the spec requires. Caught in
>   review; fixed in the committed version via the `_module_for` helper.
>   This is exactly the class of subtle off-by-one a strict-schema
>   validator can't catch — it's a contract bug, not a shape bug.
> - Type drift on zero-state numerics: `round(0, 4)` returns `int`, but
>   the spec requires `float` for spend fields. Fixed by
>   `round(float(...), 4)` coercion throughout.
>
> **Recommendation:** keep `generate → x-ai/grok-4-fast` as-is. Grok
> produced 90%-correct code on first attempt for a non-trivial task with a
> detailed specification. The bugs were subtle contract violations a human
> reviewer catches quickly. This is the exact workflow the tool was
> designed for: cheap tier writes, expensive tier reviews, expensive tier
> decides.
>
> **Schema lesson:** deliberately chose NOT to pass an `output_schema` on
> the call — the deliverable was Python source code, not JSON. Schema
> validation is appropriate for structured review/extract/classify calls
> and inappropriate for `generate` calls targeting code.

The honest summary for future sessions: Grok Fast via `cairn_delegate`
produced acceptable production code on the first attempt for a
well-specified SQLite aggregation helper. Two small bugs (one contract
violation, one type drift) were caught by Sonnet review and fixed in under
three minutes. Use `cairn_delegate` for discrete helper functions, SQL
query builders, and schema-stable extraction where the spec can be written
in under 500 words. Do not use it for multi-file refactors, cross-module
design decisions, or anything requiring holding invariants across the
codebase.

## Related

- `core/delegation/router.py` — task_type → model routing (NOT to be
  confused with `core/models/router.py`, which governs Cairn's internal
  agent loop).
- `core/delegation/cost.py` — pricing table, USD→GBP conversion.
- `core/delegation/log.py` — `cairn_delegation_log` schema and insert.
- `core/delegation/context.py` — aggregate helpers used by
  `GET /api/cairn/context`; see `_module_for` for the D-103 fix.
- `docs/cairn/LOCAL_CONVENTIONS.md` — `CLAW_API_KEY` env var, project
  naming, code layout for Cairn.
- `projects/claw/core.md` — D-103 in full (the empirical evidence this
  article summarises).
- `wiki/decisions/delegation-tier-routing.md` — decision record D-A
  through D-F plus D-101, D-102, D-103.
- `CLAUDE.md` STEP 2b Rule 1b — enforcement rule for cross-module
  delegation (this article is the pattern; the rule is the obligation).
