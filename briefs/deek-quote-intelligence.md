# Deek Brief — Quote intelligence endpoints

**Target repo:** Deek (`D:\claw` / `NBNEORIGIN/deek`)
**Module:** Deek
**Consumer:** Claude Code (Deek session) — then consumed by CRM
**Protocol:** Follow `NBNE_PROTOCOL.md`.
**Companion brief:** `briefs/crm-quote-generator.md` on the CRM
repo. That brief ships the actual quote editor + PDF + Xero
integration. This brief layers the intelligence — margin
patterns, similar past quotes, sanity-check on drafted quotes —
that the CRM editor sidebar consumes.

**Ship after** the CRM brief has merged. These endpoints are a
read-only intelligence layer over already-existing Deek state
(search_crm, retrieve_similar_decisions, CounterpartyRisk
surfaces). Until the CRM's quote UI calls them, they're inert;
safe to deploy incrementally.

---

## Why this brief exists

Deek already has the raw material — past quote text indexed via
pgvector, LessonLearned rows structured, CounterpartyRisk model
live — but no *composite intelligence API* that the CRM quote
editor can call to surface "what have we quoted for jobs like
this?" in the sidebar as the user types.

Three endpoints close that gap.

---

## Pre-flight self-check

1. Read `CLAUDE.md`, `NBNE_PROTOCOL.md`, `core.md`.
2. Confirm `core/tools/crm_tools.py`'s `_search_crm` still works
   against live CRM — that's the underlying primitive.
3. Confirm `CounterpartyRisk` rows are surfaced via the CRM's
   search. If not, the `/context` endpoint will call the CRM
   separately for risk data.
4. Confirm `core.intel.retriever.retrieve_similar_decisions`
   still covers `source_type='b2b_quote'`. That's the existing
   path for "past quote shapes".
5. Report findings before Task 1.

---

## Tasks

### Task 1 — `GET /api/deek/quotes/context`

Composite read. Given a CRM `project_id`, return everything the
quote editor should know about this client + shape of work.

```
GET /api/deek/quotes/context?project_id=<id>&query=<optional-text>

Response:
{
  "project_id": "...",
  "client": {
    "name": "...",
    "payment_record": {
      "on_time_count": 12,
      "late_count": 1,
      "disputed_count": 0,
      "counterparty_risk_band": "LOW",
      "counterparty_risk_reasoning": "..."
    },
    "prior_quotes": [
      {"quote_number": "Q-2024-00041",
       "total": 2850, "status": "accepted", "delivered_at": "..."}
    ]
  },
  "similar_jobs": [
    {"project_id": "...",
     "project_name": "Flowers by Julie fascia",
     "quoted_amount": 2850.0, "outcome": "won",
     "lead_time_days": 14,
     "match_reason": "shop fascia + window vinyl, similar scope"}
  ],
  "margin_reference": {
    "sample_size": 18,
    "quoted_range_low": 2200.0,
    "quoted_range_median": 2950.0,
    "quoted_range_high": 3800.0,
    "typical_margin_pct": 38.5
  },
  "lessons_learned": [
    {"id": "...", "title": "...",
     "summary_short": "...",
     "relevance_score": 0.72}
  ],
  "generated_at": "2026-04-22T11:00:00Z",
  "cache_ttl_seconds": 300
}
```

Composition:
- `client.*` ← pull from CRM's `Client`, `ClientBusiness`,
  `CounterpartyRisk` via `search_crm` + an optional dedicated
  call to `/api/cairn/clients/{id}/risk` if that endpoint exists
  (propose it as a CRM follow-up otherwise)
- `similar_jobs[]` ← reuse `core.triage.similar_jobs.find_similar_jobs()`
  with the project's enquiry text as the query
- `margin_reference` ← aggregate the `similar_jobs` + `prior_quotes`
  row values; median/range math here, not in the caller
- `lessons_learned[]` ← `retrieve_similar_decisions(source_type='kb')`
  ranked by cosine similarity to the project summary

### Task 2 — `GET /api/deek/quotes/similar`

Thin wrapper over `search_crm` scoped to quote rows, for the
"show me 5 quotes that look like what I'm drafting" button.

```
GET /api/deek/quotes/similar?query=<text>&limit=5

Response:
{
  "results": [
    {"quote_number": "Q-2024-00041", "project_name": "...",
     "client_name": "...", "total": 2850.0, "status": "accepted",
     "line_item_preview": "...", "match_score": 0.67}
  ]
}
```

### Task 3 — `POST /api/deek/quotes/review`

Sanity-check a drafted quote body against historical patterns.
Shadow-mode gated (`DEEK_QUOTE_REVIEW_SHADOW=true` default) for
the first two weeks — logs its output rather than returning
anything the UI surfaces.

```
POST /api/deek/quotes/review
Body: {
  "project_id": "...",
  "total_inc_vat": 2850.0,
  "line_items_summary": "3 items: supply + install + vinyl",
  "scope_summary": "Internal membership promotion signs × 3"
}

Response:
{
  "verdict": "ok" | "investigate" | "flag",
  "reasoning": "short prose",
  "signals": [
    "margin_vs_median: -12%",
    "deposit_missing",
    "client_late_history: 1/13"
  ],
  "shadow_mode": true
}
```

Implementation:
- Pull the same context as Task 1
- Compute signals: margin delta vs median, missing deposit, payment
  risk, absence of install line when install-keywords present
- Pass the full context + signals to local Qwen with a prompt that
  asks it to rate the quote OK / INVESTIGATE / FLAG + a one-sentence
  reason
- In shadow mode: log to `cairn_intel.quote_review_shadow` (new
  table, migration 0012); return `verdict: 'ok'` regardless so the
  UI doesn't interrupt the user
- Post-cutover: return the real verdict + show it as a warning
  banner in the CRM editor

Migration `0012_quote_review_shadow.sql`:
```sql
CREATE TABLE IF NOT EXISTS cairn_intel.quote_review_shadow (
  id            BIGSERIAL PRIMARY KEY,
  project_id    TEXT NOT NULL,
  total_inc_vat DECIMAL(10, 2),
  verdict       TEXT NOT NULL,
  reasoning     TEXT,
  signals       JSONB NOT NULL DEFAULT '[]'::jsonb,
  toby_verdict  TEXT,
  toby_reviewed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Cutover cron mirrors the pattern at `scripts/conversational_cutover.py`,
scheduled for 2026-05-13 (two weeks review period).

### Task 4 — Tool wrappers for chat

Add three Deek agent tools wrapping the above so Toby can ask in
chat: "what have we quoted for jobs like this project?":

- `get_quote_context(project_id)` — wraps Task 1
- `search_similar_quotes(query)` — wraps Task 2
- `review_quote_draft(project_id, total, summary)` — wraps Task 3

Same pattern as `search_crm` + `write_crm_memory` (PR #42).
Registered in `coding` and `business` permission sets.

### Task 5 — Tests

- Unit: Task 1 composition with stub CRM + stub retriever
- Unit: margin_reference math (median, range, outlier handling)
- Unit: Task 3 signal detection (margin delta threshold, deposit
  missing detection, install-keyword match)
- Integration (opt-in): live CRM call against known
  project id, expects populated `similar_jobs[]`
- Shadow-mode: `/review` returns `ok` + logs even when the
  "real" verdict would be `flag`

### Deliverable

Single PR on Deek repo:
- 3 new endpoints in `api/routes/quotes.py`
- `core/intel/quote_context.py` composition module
- 3 agent tools + schemas in `core/tools/crm_tools.py`
- Migration 0012
- Cutover cron (`scripts/quote_review_cutover.py`)
- Tests green
- `coding` / `business` permission sets updated

---

## Constraints

- No breaking changes to existing `/api/deek/*` endpoints
- `/context` p95 latency < 2s — budget 1.5s for CRM search + 500ms
  for aggregation + Qwen call; if exceeded, degrade sections
  (e.g. omit `margin_reference`) rather than stall the response
- All three endpoints accept Bearer auth via existing middleware
- Never invent historical quote data — every `similar_jobs` entry
  must trace back to an actual CRM row id
- `/review` is shadow-only until cutover; never return anything
  other than `ok` pre-cutover

---

## Out of scope

- CRM-side UI changes. That's the companion brief.
- Training a custom margin model. The median-vs-median heuristic
  is v1; a proper model is a separate brief once we have ≥100
  quotes through the flow.
- Cross-module writes (nothing in this brief mutates CRM state —
  it's pure read + local-DB shadow logging).

---

## Rules of engagement

Stay in the Deek repo. Do NOT propose new CRM write endpoints
from this brief — if something needs to land CRM-side, stop and
write a spanning brief. The CRM companion brief deliberately ships
first with zero Deek dependency; your endpoints are additive.
