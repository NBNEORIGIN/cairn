-- 0014 — Persistent email-thread ↔ CRM-project associations.
--
-- Closes the "12% match rate" gap in triage. Before: every inbound
-- email re-runs project_matcher from scratch (heuristic name+subject
-- search against CRM; fragile). After: when a thread is matched
-- once, the mapping persists, and every future message on the same
-- thread_id auto-attaches — no re-matching, no digest, direct assign.
--
-- Association is written when any of:
--   1. Toby replies YES to a triage digest (match_confirm=affirm
--      or select_candidate) — strongest signal
--   2. Toby sends a Telegram /tag <project-id> command on the last
--      drafted thread
--   3. (Future) Triage auto-matcher returns a candidate above a
--      high-confidence threshold — weaker signal, can be overridden
--      by /nottag
--
-- thread_id comes from cairn_email_raw.thread_id which is populated
-- at ingest from the In-Reply-To / References headers. For the first
-- message of a thread (no In-Reply-To) there's no association to
-- persist — the initial match still goes through the matcher, and
-- the association gets written on the FIRST reply where Toby confirms.
--
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS cairn_intel.email_thread_associations (
  id               BIGSERIAL PRIMARY KEY,
  thread_id        TEXT NOT NULL,
  project_id       TEXT NOT NULL,
  confidence       TEXT NOT NULL DEFAULT 'confirmed',
  -- 'confirmed' | 'high_auto' | 'inferred' | 'manual_tag'
  source           TEXT NOT NULL,
  -- 'triage_reply_yes' | 'telegram_tag' | 'auto_high_confidence'
  -- | 'brief_reply' | 'admin_manual'
  associated_by    TEXT,
  client_email     TEXT,     -- denormalised for client-level heuristics
  first_matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_message_at  TIMESTAMPTZ,
  message_count    INTEGER NOT NULL DEFAULT 1,
  revoked_at       TIMESTAMPTZ,
  revoked_by       TEXT,
  revoke_reason    TEXT,

  -- One (thread_id, project_id) pair max. Re-tagging the same
  -- thread to the same project is a no-op upsert. Tagging to a
  -- DIFFERENT project is allowed — creates a separate row and
  -- the most recent non-revoked row wins at lookup time.
  UNIQUE (thread_id, project_id)
);

CREATE INDEX IF NOT EXISTS email_thread_associations_thread_active_idx
  ON cairn_intel.email_thread_associations (thread_id, last_message_at DESC)
  WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS email_thread_associations_project_idx
  ON cairn_intel.email_thread_associations (project_id)
  WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS email_thread_associations_client_idx
  ON cairn_intel.email_thread_associations (client_email, first_matched_at DESC)
  WHERE revoked_at IS NULL AND client_email IS NOT NULL;
