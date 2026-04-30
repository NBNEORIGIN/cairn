"""User authentication storage for Deek + Rex.

Migrated from DEEK_USERS env var to deek_users table on 2026-04-30 so
in-app password changes + admin resets can mutate state at runtime
without env edits or container restarts. The user_store module owns
the bcrypt logic, schema bootstrap, and audit-log writes.
"""
