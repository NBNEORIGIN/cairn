"""DB-backed user store — deek_users + deek_user_audit.

Public API:

    verify_password(email, password) -> dict | None
        Return {'email', 'name', 'role'} on success, None on bad creds.

    change_password(email, old_password, new_password, *, by_email=None) -> bool
        User self-service change. Verifies old password first.

    admin_reset_password(target_email, new_password, *, by_email) -> bool
        Admin-initiated reset (no old password needed).

    list_users() -> list[dict]
        Used by /admin/users.

    ensure_schema() -> None
        Idempotent. Creates tables if missing AND seeds from
        DEEK_USERS env if deek_users is empty. Called on every
        public-API entry-point so the first call after a deploy
        bootstraps cleanly.

The schema migration in migrations/postgres/0018_deek_users.sql is
the formal record; ensure_schema() duplicates the DDL inline so the
module also works on instances where the migration hasn't run yet
(jo-pip's DB doesn't run the migrations folder on its own — it relies
on lazy schema creation in code, same pattern as deek_voice_sessions).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MIN_PASSWORD_LEN = 8


def _connect():
    import psycopg2
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None
    try:
        return psycopg2.connect(db_url, connect_timeout=5)
    except Exception as exc:
        logger.warning('[user_store] db connect failed: %s', exc)
        return None


def _normalise_email(email: str) -> str:
    return (email or '').strip().lower()


def ensure_schema() -> None:
    """Create tables if missing, seed from DEEK_USERS env on empty table."""
    conn = _connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS deek_users (
                    email VARCHAR(200) PRIMARY KEY,
                    bcrypt_hash VARCHAR(200) NOT NULL,
                    name VARCHAR(200),
                    role VARCHAR(50) NOT NULL DEFAULT 'STAFF',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS deek_user_audit (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(200) NOT NULL,
                    action VARCHAR(50) NOT NULL,
                    by_email VARCHAR(200),
                    at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_deek_user_audit_email "
                "ON deek_user_audit (email, at DESC)"
            )
            cur.execute("SELECT count(*) FROM deek_users")
            (count,) = cur.fetchone()
            if count == 0:
                _seed_from_env(cur)
        conn.commit()
    except Exception as exc:
        logger.warning('[user_store] ensure_schema failed: %s', exc)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def _seed_from_env(cur) -> None:
    """Parse DEEK_USERS env and insert into deek_users.

    Format: ``email|bcrypt_hash|name|role`` records, semicolon-separated.
    Logs an audit row per seeded user.
    """
    raw = os.getenv('DEEK_USERS', '').strip().strip("'\"")
    if not raw:
        return
    seeded = 0
    for record in raw.split(';'):
        record = record.strip()
        if not record:
            continue
        parts = [p.strip() for p in record.split('|')]
        if len(parts) < 4:
            continue
        email, bcrypt_hash, name, role = parts[0], parts[1], parts[2], parts[3]
        email = _normalise_email(email)
        if not email or not bcrypt_hash:
            continue
        try:
            cur.execute(
                "INSERT INTO deek_users (email, bcrypt_hash, name, role) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (email) DO NOTHING",
                (email, bcrypt_hash, name, role),
            )
            cur.execute(
                "INSERT INTO deek_user_audit (email, action, by_email) "
                "VALUES (%s, 'seed', NULL)",
                (email,),
            )
            seeded += 1
        except Exception as exc:
            logger.warning('[user_store] seed row %s failed: %s', email, exc)
    if seeded:
        logger.info('[user_store] seeded %d users from DEEK_USERS env', seeded)


def verify_password(email: str, password: str) -> Optional[dict]:
    """Return user record if credentials valid, else None."""
    if not email or not password:
        return None
    ensure_schema()
    email = _normalise_email(email)
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, bcrypt_hash, name, role "
                "FROM deek_users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    db_email, bcrypt_hash, name, role = row
    try:
        import bcrypt
        ok = bcrypt.checkpw(
            password.encode('utf-8'),
            bcrypt_hash.encode('utf-8'),
        )
    except Exception as exc:
        logger.warning('[user_store] bcrypt verify failed for %s: %s', email, exc)
        return None
    if not ok:
        return None
    return {'email': db_email, 'name': name or db_email, 'role': role}


def change_password(
    email: str,
    old_password: str,
    new_password: str,
    *,
    by_email: Optional[str] = None,
) -> bool:
    """Self-service: verify old password, set new. Returns True on success."""
    if len(new_password or '') < _MIN_PASSWORD_LEN:
        return False
    user = verify_password(email, old_password)
    if not user:
        return False
    return _set_password(
        _normalise_email(email),
        new_password,
        by_email=_normalise_email(by_email or email),
        action='change',
    )


def admin_reset_password(
    target_email: str,
    new_password: str,
    *,
    by_email: str,
) -> bool:
    """Admin reset: no old-password check. Returns True if user existed."""
    if len(new_password or '') < _MIN_PASSWORD_LEN:
        return False
    return _set_password(
        _normalise_email(target_email),
        new_password,
        by_email=_normalise_email(by_email),
        action='admin_reset',
    )


def _set_password(email: str, new_password: str, *, by_email: str, action: str) -> bool:
    import bcrypt
    new_hash = bcrypt.hashpw(
        new_password.encode('utf-8'),
        bcrypt.gensalt(rounds=10),
    ).decode('utf-8')
    conn = _connect()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE deek_users SET bcrypt_hash = %s, updated_at = NOW() "
                "WHERE email = %s",
                (new_hash, email),
            )
            updated = cur.rowcount
            if updated:
                cur.execute(
                    "INSERT INTO deek_user_audit (email, action, by_email) "
                    "VALUES (%s, %s, %s)",
                    (email, action, by_email),
                )
        conn.commit()
        return updated > 0
    except Exception as exc:
        logger.warning('[user_store] set_password failed for %s: %s', email, exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def list_users() -> list[dict]:
    """Return all users (for /admin/users). Excludes bcrypt_hash."""
    ensure_schema()
    conn = _connect()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, name, role, created_at, updated_at "
                "FROM deek_users ORDER BY email"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            'email': r[0],
            'name': r[1],
            'role': r[2],
            'created_at': r[3].isoformat() if r[3] else None,
            'updated_at': r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


__all__ = [
    'ensure_schema',
    'verify_password',
    'change_password',
    'admin_reset_password',
    'list_users',
]
