# Crosslink graph

Deek's memory layer now carries an entity graph alongside salience
and recency. Entities (customers, suppliers, SKUs, materials,
modules, error types, job numbers) become nodes; co-occurrence across
memories becomes edges. Later phases will walk the graph at retrieval
to surface structurally-related memories that pure cosine similarity
misses.

Status: **Phase A — graph populated, retrieval unchanged**. Every new
memory write extracts entities and reinforces the graph; the existing
16 memory rows are backfilled via `scripts/seed_entity_graph.py`.
Graph walk at retrieval + 4-way RRF fusion is Phase B; cutover is
Phase C.

## Entity taxonomy

`config/entity_taxonomy.yaml` defines the types Deek recognises, the
extraction method for each, and the stop-entity blocklist.

| Type | Source | Notes |
|---|---|---|
| `m_number` | regex `\bM\d{4,5}\b` | NBNE job numbers. Stable, high-signal. |
| `module` | `DEEK_MODULES.yaml` | Pulled via `core.identity.assembler`. |
| `customer` | `config/customers.yaml` | Toby-curated. CRM sync is Phase B+. |
| `supplier` | `config/suppliers.yaml` | As above. |
| `material` | `config/materials.yaml` | As above. |
| `error_type` | regex | Common error class names / HTTP codes. |

### Canonicalisation

Canonical form = `lower().strip()` with whitespace collapsed.
`"Flowers By Julie"` and `"flowers by julie"` resolve to the same
node. Unique key in the DB is `(type, canonical_name)`.

### Stop entities

Too ubiquitous to carry signal; a walk through them matches
everything. Default blocklist:

```
toby, jo, deek, nbne, cairn, claude, claude code, deek agent
```

Additions require a PR to `config/entity_taxonomy.yaml`.

## Schema

`migrations/postgres/0002_crosslink_graph.sql`:

- `entity_nodes(id uuid, type, canonical_name, display_name, aliases[], mention_count, first_seen, last_seen)` — `UNIQUE(type, canonical_name)`
- `entity_edges(source_id, target_id, weight, co_occurrence_count, outcome_signal, last_reinforced)` — PK `(source_id, target_id)` with `CHECK source_id < target_id` so each undirected pair is stored once
- `memory_entities(memory_id INTEGER REFERENCES claw_code_chunks(id), entity_id uuid)` — the link table. INTEGER (not UUID) because Deek's memory store is `claw_code_chunks`, not the imaginary `memory_entries` the brief assumed.

## Write path

`api/main.py::_embed_memory_to_pgvector` now calls into
`core.memory.entities.upsert_entities_and_edges` inside the same
transaction as the memory insert. Failure to extract entities is
non-fatal — logged via `logger.warning` and the memory still writes
cleanly without graph links.

### Edge math

- `co_occurrence_count` increments on every reinforcement
- `weight = LEAST(10, weight + 1/(count+1))` — diminishing returns
- `outcome_signal` = running mean of memory outcomes on the edge, in
  `[-1, +1]` (fail = -1, success = +1, unknown = 0)

## Curating the canonical lists

Three files in `config/`:

- `customers.yaml`
- `suppliers.yaml`
- `materials.yaml`

Each entry has a `canonical` display name and an optional `aliases`
list. Short aliases (<3 chars) are skipped at extraction time to
avoid noise. Word-boundary matching prevents substring hits.

To grow the lists:

1. Edit the YAML file
2. Open a PR
3. After merge + deploy, the next API restart picks up the new entries
4. Optionally re-run `scripts/seed_entity_graph.py` to retroactively
   extract the newly-canonical entities from existing memories
   (idempotent — already-populated pairs are no-ops)

## Inspecting the graph (Phase B+)

Diagnostic endpoints land in Phase B:

- `GET /api/deek/memory/graph/stats` — node count by type, top-10
  edge weights, orphan count
- `GET /api/deek/memory/graph/entity/{id}` — 2-hop neighbourhood
- `GET /api/deek/memory/graph/walk?query=...` — show the walk for a
  given query

Until then, direct SQL against `entity_nodes` / `entity_edges` is the
way to see state.

## Scale expectation (2026-04-19)

16 memory rows today. Graph will be small (<100 nodes, <500 edges)
after Phase A seeds. The brief's pass gate for "structural analogy"
tests is likely to be unreachable at this scale — the infrastructure
is correct but there aren't enough memories yet for cross-domain
patterns to emerge. Revisit when memory volume reaches ~100+.

## Not in Phase A

- Graph walk at retrieval → Phase B
- 4-way RRF fusion (BM25 + pgvector episodic + pgvector schemas + graph) → Phase B
- Diagnostic endpoints → Phase B
- Shadow-mode review → Phase C
- `NBNE_PROTOCOL.md` patch → Phase C
