-- 0018_deek_users.sql
--
-- Move user credentials from the DEEK_USERS env var to a database table,
-- so password changes / admin resets can happen at runtime without
-- editing files on the host or restarting containers.
--
-- Bootstrap: on the first API boot after this migration runs, if
-- deek_users is empty, core.auth.user_store seeds it by parsing the
-- existing DEEK_USERS env var. After that the table is the source of
-- truth — env value becomes a fallback only.
--
-- Schema notes:
--   * email is the natural primary key (lowercase'd at write time —
--     enforced in the user_store layer, not at the DB). Single-tenant
--     for now.
--   * bcrypt_hash holds an exact "$2a$..." / "$2b$..." string from
--     bcrypt.hashpw(..., gensalt(rounds=10)). 60 chars is the canonical
--     length but we allow up to 200 for forward-compatibility.
--   * role values: ADMIN | PM | STAFF | READONLY | CLIENT (matches the
--     Role union in web/src/lib/auth.ts).
--   * deek_user_audit logs every set/change/reset for traceability.
--     Append-only; queryable when "who reset Jo's password" comes up.
--
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS deek_users (
  email         VARCHAR(200) PRIMARY KEY,
  bcrypt_hash   VARCHAR(200) NOT NULL,
  name          VARCHAR(200),
  role          VARCHAR(50) NOT NULL DEFAULT 'STAFF',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS deek_user_audit (
  id            SERIAL PRIMARY KEY,
  email         VARCHAR(200) NOT NULL,
  action        VARCHAR(50) NOT NULL,        -- 'seed' | 'change' | 'admin_reset'
  by_email      VARCHAR(200),                -- who triggered it (self for change, admin for reset)
  at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deek_user_audit_email
  ON deek_user_audit (email, at DESC);
