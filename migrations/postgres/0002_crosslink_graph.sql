-- 0002_crosslink_graph.sql
--
-- Brief 3 Phase A (Crosslink Graph) — entity nodes + edges, plus a
-- link table between memories and their extracted entities.
--
-- Memory FK points at claw_code_chunks(id) as INTEGER because that's
-- where memory actually lives — the brief's UUID assumption against
-- a nonexistent memory_entries table does not match the deployed
-- schema.
--
-- See docs/CROSSLINK_GRAPH.md and briefs/DEEK_BRIEF_3_CROSSLINK_GRAPH.md.
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS entity_nodes (
  id UUID PRIMARY KEY,
  type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  aliases TEXT[] NOT NULL DEFAULT '{}'::text[],
  first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  mention_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE (type, canonical_name)
);

CREATE INDEX IF NOT EXISTS ix_entity_nodes_type ON entity_nodes (type);
CREATE INDEX IF NOT EXISTS ix_entity_nodes_canonical ON entity_nodes (canonical_name);

-- Edges are undirected in spirit but stored with deterministic
-- (source_id, target_id) ordering so we only store each pair once.
-- Convention: source_id < target_id (UUID lexicographic).
CREATE TABLE IF NOT EXISTS entity_edges (
  source_id UUID NOT NULL REFERENCES entity_nodes(id) ON DELETE CASCADE,
  target_id UUID NOT NULL REFERENCES entity_nodes(id) ON DELETE CASCADE,
  weight REAL NOT NULL DEFAULT 1.0,
  co_occurrence_count INTEGER NOT NULL DEFAULT 1,
  outcome_signal REAL NOT NULL DEFAULT 0.0,  -- running mean in [-1, +1]
  last_reinforced TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (source_id, target_id),
  CHECK (source_id < target_id)
);

CREATE INDEX IF NOT EXISTS ix_entity_edges_source ON entity_edges (source_id);
CREATE INDEX IF NOT EXISTS ix_entity_edges_target ON entity_edges (target_id);
CREATE INDEX IF NOT EXISTS ix_entity_edges_weight ON entity_edges (weight DESC);

-- memory_entities — the link table. memory_id is INTEGER, not UUID,
-- because the real memory store is claw_code_chunks.
CREATE TABLE IF NOT EXISTS memory_entities (
  memory_id INTEGER NOT NULL REFERENCES claw_code_chunks(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entity_nodes(id) ON DELETE CASCADE,
  PRIMARY KEY (memory_id, entity_id)
);

CREATE INDEX IF NOT EXISTS ix_memory_entities_memory ON memory_entities (memory_id);
CREATE INDEX IF NOT EXISTS ix_memory_entities_entity ON memory_entities (entity_id);
