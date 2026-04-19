# Impressions layer

Deek's retrieval layer weights memories by **relevance × salience ×
recency**, not relevance alone. Strong impressions last longer;
unused memories fade; repetition becomes schema.

Status: **Phase A — shadow mode**. The ranker computes the new ordering
on every retrieval but returns the OLD ordering to callers. Shadow
data lands in `data/impressions_shadow.jsonl` for review before the
flip.

## Three components

### 1. Salience at write time

`core/memory/salience.py` scores each memory write on five signals:

| Signal | Weight | What it catches |
|---|---:|---|
| `money` | 2.5 | numeric amounts in £/$/€, log-scaled |
| `customer_pushback` | 2.0 | keyword-based friction (complaint, refund, escalate, rework) |
| `outcome_weight` | 3.0 | explicit outcome — failures and deferrals score higher than wins |
| `novelty` | 1.5 | `1 − max_cosine` against the last 100 memories |
| `toby_flag` | 5.0 | hard star flag in metadata |

Weights live in `config/salience.yaml`. The extractor runs **only** on
memory-bearing chunk types (`memory`, `email`, `wiki`,
`module_snapshot`, `social_post`). Code chunks keep `salience = 1.0`
so retrieval ordering cannot downgrade code relative to where it was
pre-Brief-2.

Final salience is `base_score + Σ(weight × signal)`, clipped to
[0, 10]. Budget: <50ms median per write, no LLM call.

### 2. Reranking at retrieval time

`core/memory/impressions.py::rerank()` applies after RRF fusion:

```
final = α · relevance + β · salience + γ · recency
```

Each term is min-max normalised within the candidate set, so weights
are meaningful regardless of absolute RRF score magnitude. Defaults:

```yaml
# config/retrieval.yaml
alpha: 0.5       # relevance
beta:  0.25      # salience
gamma: 0.25      # recency
tau_hours: 72.0  # recency half-life
top_k: 20
```

`recency = exp(-hours_since_last_access / tau)`. With `tau = 72`,
a memory read 3 days ago scores 0.37 on recency; one read just now
scores 1.0.

### 3. Reinforcement

Every retrieval that returns a memory-bearing chunk triggers an
async write-back:

```
access_count       += 1
last_accessed_at    = NOW()
salience            = min(10.0, salience + 0.1)
```

Fire-and-forget on a daemon thread so it never blocks the response.
Only reinforces memory-bearing chunks — code chunks don't gain
salience from being read.

## Shadow mode

Controlled by `DEEK_IMPRESSIONS_SHADOW` (default `true`). When shadow:

- Ranker runs, new ordering computed
- Old (pre-Brief-2) ordering is returned to the caller
- A JSONL record lands in `data/impressions_shadow.jsonl` with
  both top-5s and the per-candidate signal breakdown

Review the shadow log; once satisfied the new ordering is better,
set `DEEK_IMPRESSIONS_SHADOW=false` and redeploy.

## Schema

Migration `migrations/postgres/0001_impressions_layer.sql` adds:

- `claw_code_chunks.salience REAL DEFAULT 1.0`
- `claw_code_chunks.last_accessed_at TIMESTAMPTZ DEFAULT NOW()`
- `claw_code_chunks.access_count INTEGER DEFAULT 0`
- `claw_code_chunks.salience_signals JSONB DEFAULT '{}'`
- New `schemas` table (populated in Phase B by the nightly
  consolidation job — empty for now)

Applied automatically at API startup by
`core/memory/migrations.py`. Idempotent — safe to re-run.

## Not in Phase A

- Nightly consolidation → Brief 2 Phase B
- Schema retrieval (reading from `schemas` during relevant queries) → Phase B
- Diagnostic endpoints (`/memory/salience/distribution` etc.) → Phase B
- Flipping off shadow mode → Phase C after 1 week of shadow data

## Files

```
core/memory/salience.py          extractor + signal scorers
core/memory/impressions.py       rerank + reinforcement + shadow
core/memory/migrations.py        Postgres migration bootstrapper
config/salience.yaml             weights
config/retrieval.yaml            rerank weights + tau
migrations/postgres/             numbered idempotent SQL
tests/memory/                    unit tests (47 passing)
```

## Tuning

Both config files hot-apply on next API restart. Start with the
defaults; after 1 week of shadow data you'll know whether `alpha`
should be higher (retrieval is already well-targeted) or lower
(salience and recency add genuine signal). Log lives at
`data/impressions_shadow.jsonl`.
