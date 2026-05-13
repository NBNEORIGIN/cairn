-- Phase 5 of the inbox learning loop (2026-05-13).
--
-- A learned, dynamic sender ↔ project memory. Distinct from CRM's
-- static project.clientEmail field — that's the address Toby typed
-- in once when creating the project. THIS table is what Deek has
-- *observed* over time: every confirmed reply, every reassign, every
-- archive on a matched draft adds a vote.
--
-- The matcher consults this table BEFORE running fuzzy CRM search.
-- A sender with strong evidence for a single project skips the
-- fuzzy step entirely. A sender with weak evidence still gets a
-- score boost on the fuzzy candidates. A sender with no evidence
-- falls through to today's behaviour.
--
-- Three counters per (sender_email, project_id) row, each a different
-- signal strength:
--
--   confirmations  — Toby archived ('Mark done') OR staged a draft
--                    that Deek had already matched to this project.
--                    The strongest positive: "you got it right and I
--                    sent the reply".
--
--   overrides      — Toby explicitly *reassigned* this email to this
--                    project from somewhere else (or from no match).
--                    Stronger than confirmations because Toby took
--                    an explicit action to correct.
--
--   rejections     — Toby reassigned AWAY from this project (the
--                    project was the prior assignment that he
--                    rejected). Negative evidence.
--
-- The scoring function lives in core.triage.sender_associations.

CREATE TABLE IF NOT EXISTS cairn_intel.sender_project_associations (
    id              BIGSERIAL    PRIMARY KEY,
    sender_email    TEXT         NOT NULL,
    project_id      TEXT         NOT NULL,
    confirmations   INTEGER      NOT NULL DEFAULT 0,
    overrides       INTEGER      NOT NULL DEFAULT 0,
    rejections      INTEGER      NOT NULL DEFAULT 0,
    first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (sender_email, project_id)
);

CREATE INDEX IF NOT EXISTS sender_project_associations_sender_idx
    ON cairn_intel.sender_project_associations (sender_email);

CREATE INDEX IF NOT EXISTS sender_project_associations_project_idx
    ON cairn_intel.sender_project_associations (project_id);

-- Touch-up: keep last_seen_at honest. Cheap trigger so callers don't
-- have to remember.
CREATE OR REPLACE FUNCTION cairn_intel.spa_touch_last_seen()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_seen_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS spa_touch_last_seen ON cairn_intel.sender_project_associations;
CREATE TRIGGER spa_touch_last_seen
    BEFORE UPDATE ON cairn_intel.sender_project_associations
    FOR EACH ROW EXECUTE FUNCTION cairn_intel.spa_touch_last_seen();

COMMENT ON TABLE cairn_intel.sender_project_associations IS
    'Learned sender ↔ project memory (Phase 5 of inbox learning loop). '
    'Written by core.triage.sender_associations.record_action on every '
    'archive/stage/reassign. Read by project_matcher BEFORE fuzzy CRM search.';
