-- 0008_response_audit_validation_columns.sql
--
-- Validator-leak bug-fix (briefs/validator-leak-and-contamination-fix.md):
-- extend model_response_audit with the validation outcome so we can
-- see, without reproducing live, how often CHECK 3 et al. fire, how
-- often a retry recovers, and how often the user ends up on the
-- fallback.
--
-- Extends migration 0006 rather than creating a separate
-- validation_rejections table — fewer joins when asking "what
-- happened in this session?".
--
-- Idempotent. Safe to re-run.

ALTER TABLE model_response_audit
  ADD COLUMN IF NOT EXISTS validation_failures     TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS validation_retry_count  INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS validation_final_outcome TEXT;
  -- 'passed' | 'retry_succeeded' | 'retry_exhausted_fallback' | 'hard_fail'

CREATE INDEX IF NOT EXISTS ix_model_response_audit_validation_outcome
  ON model_response_audit (validation_final_outcome, created_at DESC)
  WHERE validation_final_outcome IS NOT NULL
    AND validation_final_outcome <> 'passed';
