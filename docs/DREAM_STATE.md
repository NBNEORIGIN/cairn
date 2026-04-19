# Dream state

Overnight, Deek samples high-salience recent memories, pulls distant
graph-connected companions, generates speculative patterns at high
temperature on the local model, and **aggressively filters** them.
A handful of survivors surface in the PWA morning briefing where
Toby accepts, rejects, edits, or defers. Accepted candidates promote
to `schemas` — the same table consolidation writes to. Rejected
candidates train the duplication gate.

Design principle: **free association produces plausible nonsense by
default. The value is in the filter.** Budget ~100 attempts in → ~3
surface. Every surfaced candidate cites specific source memory IDs
and is falsifiable on inspection.

Status: **Phase C — complete**. Every layer live: nocturnal
generation, morning surface, PWA review, schema promotion, stale
sweep, schema decay, daily digest. Nothing deferred except the
`nbne-policy#3` doc patch (open; merges when Toby does).

## Mechanism

### 1. Seed selection

Top N=20 memories from the last 30 days ranked by
`salience × exp(-hours_since_access / 72h)` — same ranking as the
consolidation job (`core/memory/consolidation.py`).

### 2. Distant-pair generation

For each seed, find companions that:

- Share at least one entity with the seed (via `memory_entities`)
- Have cosine similarity to the seed `< 0.4` (topically distant)
- Come from the broader memory pool, not just other seeds

Top 3–5 companions by `(1 − similarity) × salience` become the
bundle. Bundles with fewer than 3 members are dropped.

### 3. Candidate generation

For each bundle, prompt the local LLM (default `qwen2.5:7b-instruct`
via Tailscale to deek-gpu) at temperature 0.9 with
`core/dream/prompts/v1_dream.txt`. The prompt accepts `candidate:
null` for "no pattern" and requires JSON-formatted positive
responses citing ≥3 memory IDs from the bundle.

### 4. Filter

`core/dream/filter.py` runs four gates in order. Candidates failing
any gate are dropped with a breakdown in `filter_signals`:

| Gate | What it catches |
|---|---|
| **Grounding** | <3 sources, or candidate's key terms don't appear in cited memories |
| **Specificity** | Anti-pattern match (platitudes like "customers prefer", "reduce costs") |
| **Actionability** | No entity / channel / price / decision keyword / timeframe |
| **Duplication** | Cosine > 0.85 vs existing active schemas or recent rejected candidates |

`config/dream/anti_pattern_list.yaml` grows over time — each entry
is a data point about what "too generic" means in NBNE's context.

### 5. Scoring

```
score = 0.4 * confidence
      + 0.2 * min(1.0, source_memory_count / 10)
      + 0.2 * entity_type_diversity
      + 0.2 * (1.0 if actionability_ok else 0.0)
```

`entity_type_diversity`: 1.0 if sources span 3+ entity types, 0.6
for 2, 0.3 for 1, 0 otherwise.

Top K by score → surfaced (`surfaced_at = NOW()`). Others persist
for retrospective review.

## Schema

`migrations/postgres/0003_dream_candidates.sql`:

```
dream_candidates(
  id UUID PRIMARY KEY,
  candidate_text TEXT,
  candidate_type TEXT,            -- pattern | rule | analogy | prediction
  source_memory_ids INTEGER[],    -- claw_code_chunks.id
  source_entity_ids UUID[],       -- entity_nodes.id
  generation_temperature REAL,
  generation_model TEXT,
  confidence REAL,
  filter_signals JSONB,           -- per-gate breakdown
  score REAL,
  generated_at TIMESTAMPTZ,
  surfaced_at TIMESTAMPTZ,        -- NULL if not in top K
  reviewed_at TIMESTAMPTZ,
  review_action TEXT,             -- accepted|rejected|edited|deferred|expired
  review_notes TEXT,
  promoted_schema_id UUID REFERENCES schemas(id)
)
```

## Running manually

```bash
# Full run
python scripts/dream_nightly.py

# Dry run — everything except the DB writes
python scripts/dream_nightly.py --dry-run

# Smaller seed set for testing
python scripts/dream_nightly.py --seed-limit 5 --max-attempts 10
```

Cost: zero cloud calls; all inference local.

## Scale caveat

At 16 memories and 6 entity graph nodes, the loop will produce
**zero or near-zero candidates most nights**. That's not a bug.
Seeds exist, bundles may form, but either no shared entities surface
distant companions, or the filter kills the generator's output.
Build now; observe; tune once memory volume reaches ~100+.

## Phase B additions

### Cron (installed 2026-04-19)

```cron
# Deek dream state — nightly nocturnal loop
30 2 * * * docker exec -w /app -e PYTHONPATH=/app deploy-deek-api-1 \
  python scripts/dream_nightly.py \
  >> /var/log/deek-dream.log 2>&1
```

Fires at 02:30 UTC — 30 minutes after the consolidation cron — so
schemas written by consolidation are visible to the dedupe gate
during the same pass.

### `GET /api/deek/briefing/morning`

Returns the top-K unreviewed surfaced candidates from the most
recent run. Empty candidates array when there's nothing to show:

```json
{
  "date": "2026-04-19",
  "candidates": [
    {
      "id": "uuid",
      "text": "Jobs involving ACM on listed buildings ...",
      "type": "pattern",
      "confidence": 0.82,
      "score": 0.71,
      "source_memory_ids": [42623, 42624, 42933],
      "source_summaries": [
        {"memory_id": 42623, "text": "..."},
        ...
      ],
      "generated_at": "2026-04-19T02:30:17Z",
      "actions": ["accept", "reject", "edit", "defer"]
    }
  ]
}
```

### `POST /api/deek/briefing/candidate/{id}/review`

Body: `{action: "accept"|"reject"|"edit"|"defer", notes?: string, edited_text?: string}`.

- **accept** — marks reviewed, embeds the candidate text,
  creates a `schemas` row with `status='active'`, sets
  `promoted_schema_id`. Retrievable immediately.
- **edit** — same as accept but promotes the `edited_text` instead.
- **reject** — marks reviewed; candidate lives on as a negative
  example for future duplication-gate comparisons.
- **defer** — clears `surfaced_at` so the next morning re-surfaces
  the candidate. `reviewed_at` stays NULL.

### PWA Brief tab

`BriefingView.tsx` now shows an "Overnight" section above the
live briefing. Each card has:

- Candidate type + confidence
- Plain-English statement
- Expandable source-memory summaries
- Four buttons: Accept / Reject / Edit / Defer
- Edit opens inline textarea; Save commits edited text as the
  promoted schema

Empty state: *"No candidates survived the filter. Memory is the
product — some nights there's nothing worth saying."*

## Phase C additions

### Maintenance cron

Runs daily at 03:00 UTC, 30 minutes after the nocturnal loop has
finished:

```cron
# Deek dream state — daily maintenance (Brief 4 Phase C)
# Expires stale candidates (7d unreviewed), ages schemas
# (active → dormant @ 90d, dormant → archived @ 180d),
# sends the digest email.
0 3 * * * docker exec -w /app -e PYTHONPATH=/app deploy-deek-api-1 \
  python scripts/dream_maintenance.py \
  >> /var/log/deek-dream-maint.log 2>&1
```

Safe to run manually at any time (`--dry-run` reports without
applying). Zero external dependencies — SMTP is optional.

### Stale-candidate sweep

Candidates surfaced for >= 7 days without a review action are
marked `review_action='expired'`, `reviewed_at=NOW()`. If >50% of
the week's surfaced candidates expire, the digest includes a
`⚠ EXPIRED RATE > 50%` warning — either the briefing isn't being
read or the filter is too permissive.

### Schema decay

| Transition | Rule | Effect |
|---|---|---|
| active → dormant | not accessed in 90 days | still retrievable, half weight (0.75× vs 1.5×) |
| dormant → archived | not accessed in 180 days | not retrieved by default |
| dormant → active | any retrieval + reinforcement | automatic on hit |

Reactivation is handled by the retrieval path (`core/memory/
schema_retrieval.py::_reinforce_schemas_sync`) — a dormant schema
that gets retrieved bumps its `last_accessed_at`, increments
`access_count`, nudges salience, AND flips status back to `active`
in the same UPDATE. The next decay sweep then leaves it alone.

### Duplication gate learns from rejects

`core/dream/filter.py::_fetch_existing_embeddings` now pulls both:

- **All non-archived schema embeddings** (active + dormant)
- **Recently-rejected dream candidate embeddings** (last 30 days)

Each candidate is embedded at write time and the embedding stored
in `dream_candidates.embedding`. Reject a candidate once and the
pattern can't resurface for at least 30 days — the filter
calibrates from Toby's judgement.

### Daily digest

Printed to stdout and — if `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS`
are set — emailed to `DEEK_DREAM_DIGEST_TO` (default
`toby@nbnesigns.com`). Shape:

```
Deek dream-state digest — 2026-04-27
============================================================

Last night's run (2026-04-27):
  candidates generated: 5
  surfaced:             3
  actions so far:       1 accepted · 1 rejected · 0 deferred · 0 expired

Stale-candidate sweep:
  expired this run: 0 (of 12 surfaced in last 7 days = 0.0%)

Schema lifecycle:
  active:   14   dormant: 2   archived: 0

— Deek
```

SMTP reuses the shared transactional path the email-triage sender
already uses. No Postmark SDK dep needed.

### Policy patch

`NBNEORIGIN/nbne-policy#3` — Dream State section stacked on #2
(crosslink) which stacks on #1 (identity+impressions). Merge in
order: 1 → 2 → 3. When all three are merged, `sync-policy.sh` on
the next deploy pulls all three new sections into the deek repo's
vendored `NBNE_PROTOCOL.md`.

## Files

```
core/dream/__init__.py
core/dream/nocturnal.py           seed → bundle → generate → persist
core/dream/filter.py              grounding / specificity / actionability / dedupe + scoring
core/dream/prompts/v1_dream.txt   prompt template
config/dream/anti_pattern_list.yaml
scripts/dream_nightly.py          entry point
migrations/postgres/0003_dream_candidates.sql
tests/memory/test_dream_filter.py
```
