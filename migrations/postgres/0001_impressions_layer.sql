-- 0001_impressions_layer.sql
--
-- Brief 2 Phase A (Impressions Layer) — salience + recency columns on
-- the retrievable chunk store, plus a separate `schemas` table for
-- nightly consolidation output (Phase B will populate this).
--
-- See docs/IMPRESSIONS.md and briefs/DEEK_BRIEF_2_IMPRESSIONS_LAYER.md.
--
-- Idempotent. Safe to re-run.

-- ── claw_code_chunks: salience, recency, reinforcement counter ────────
-- The extractor (core/memory/salience.py) only fires on memory-bearing
-- chunk types (memory, email, wiki, module_snapshot, social_post).
-- Code chunks (window, section, function, classdef, async_function)
-- stay at salience=1.0 so retrieval ranking cannot downgrade code
-- relative to where it is today.
ALTER TABLE claw_code_chunks ADD COLUMN IF NOT EXISTS salience REAL NOT NULL DEFAULT 1.0;
ALTER TABLE claw_code_chunks ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE claw_code_chunks ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE claw_code_chunks ADD COLUMN IF NOT EXISTS salience_signals JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS ix_chunks_salience ON claw_code_chunks (salience DESC);
CREATE INDEX IF NOT EXISTS ix_chunks_last_accessed ON claw_code_chunks (last_accessed_at DESC);

-- ── schemas: distilled patterns derived from recent memories ──────────
-- Populated by the nightly consolidation job in Phase B; created here
-- so Phase A migrations close the schema gap in one shot.
--
-- Requires the pgvector extension (already installed for
-- claw_code_chunks.embedding).
CREATE TABLE IF NOT EXISTS schemas (
  id UUID PRIMARY KEY,
  schema_text TEXT NOT NULL,
  embedding vector(768),
  salience REAL NOT NULL DEFAULT 1.0,
  source_memory_ids INTEGER[] NOT NULL,    -- FK-style: claw_code_chunks.id
  derived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  access_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',    -- 'active' | 'dormant' | 'archived'
  model TEXT NOT NULL,                       -- local model that produced it
  confidence REAL NOT NULL                   -- filter score 0–1
);

CREATE INDEX IF NOT EXISTS ix_schemas_embedding ON schemas USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);
CREATE INDEX IF NOT EXISTS ix_schemas_salience ON schemas (salience DESC);
CREATE INDEX IF NOT EXISTS ix_schemas_status ON schemas (status) WHERE status = 'active';
