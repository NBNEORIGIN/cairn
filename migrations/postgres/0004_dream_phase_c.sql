-- 0004_dream_phase_c.sql
--
-- Brief 4 Phase C — infrastructure for:
--   * Duplication gate to dedupe against recently-rejected candidates
--     (needs candidate embeddings stored alongside the text)
--   * Fast lookup of candidates to expire / surface / digest
--
-- Schema decay (Task 10) needs no new columns — the existing
-- `schemas.status` + `schemas.last_accessed_at` are enough; the
-- maintenance script transitions rows based on them.
--
-- Idempotent. Safe to re-run.

ALTER TABLE dream_candidates ADD COLUMN IF NOT EXISTS embedding vector(768);

CREATE INDEX IF NOT EXISTS ix_dream_candidates_embedding
  ON dream_candidates USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50)
  WHERE embedding IS NOT NULL;

-- Index supporting the stale-candidate sweep query
-- (surfaced but unreviewed after N days).
CREATE INDEX IF NOT EXISTS ix_dream_candidates_stale_sweep
  ON dream_candidates (generated_at)
  WHERE reviewed_at IS NULL AND surfaced_at IS NOT NULL;

-- Index supporting rejected-dedupe lookup (recent rejected candidates
-- with embeddings are compared in the duplication gate).
CREATE INDEX IF NOT EXISTS ix_dream_candidates_rejected_recent
  ON dream_candidates (reviewed_at DESC)
  WHERE review_action = 'rejected' AND embedding IS NOT NULL;
