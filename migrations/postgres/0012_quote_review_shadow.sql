-- 0012 — Quote review shadow table.
--
-- POST /api/deek/quotes/review runs a local-Qwen sanity check on
-- a drafted quote against historical patterns. For the first two
-- weeks it's shadow-mode-gated (DEEK_QUOTE_REVIEW_SHADOW=true):
-- the verdict is computed and logged here, but the API always
-- returns 'ok' so the CRM quote editor doesn't yet surface
-- potentially-wrong warnings to the user.
--
-- Cutover cron scheduled for 2026-05-13, gated on
-- (>= 20 rows AND >= 72h span) — same pattern as impressions /
-- crosslink / similarity / conversational.
--
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS cairn_intel.quote_review_shadow (
  id             BIGSERIAL PRIMARY KEY,
  project_id     TEXT NOT NULL,
  total_inc_vat  DECIMAL(10, 2),
  verdict        TEXT NOT NULL,       -- ok | investigate | flag
  reasoning      TEXT,
  signals        JSONB NOT NULL DEFAULT '[]'::jsonb,
  context_used   JSONB NOT NULL DEFAULT '{}'::jsonb,  -- truncated context dump for audit
  toby_verdict   TEXT,                -- good | partial | wrong, after human review
  toby_reviewed  BOOLEAN NOT NULL DEFAULT FALSE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS quote_review_shadow_project_idx
  ON cairn_intel.quote_review_shadow (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS quote_review_shadow_unreviewed_idx
  ON cairn_intel.quote_review_shadow (created_at DESC)
  WHERE toby_reviewed = FALSE;

CREATE INDEX IF NOT EXISTS quote_review_shadow_verdict_idx
  ON cairn_intel.quote_review_shadow (verdict, created_at DESC)
  WHERE verdict <> 'ok';
