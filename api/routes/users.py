"""User-management endpoints — verify credentials, change password,
admin reset, list users.

Mounted under /api/deek/users/* by api/main.py. The Next.js login
proxy forwards (email, password) to /verify; the change-password modal
hits /me/password; the /admin/users page hits /admin/reset and /list.

Authentication: ALL endpoints require the X-API-Key header (the same
backend-protection pattern every /api/deek/* route uses). The Next.js
proxies layer in JWT cookie auth before forwarding so the public web
surface stays session-cookie-gated.

The actual ADMIN-vs-USER role check happens at the proxy layer too —
it reads session.role from the JWT and refuses /admin/* calls for
non-ADMINs. The backend trusts the proxy's authorisation decision
(same pattern as every other /admin/* endpoint in this codebase).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import verify_api_key
from core.auth import user_store

log = logging.getLogger(__name__)
router = APIRouter(prefix='/users', tags=['User auth'])


# ── /verify ──────────────────────────────────────────────────────────


class VerifyRequest(BaseModel):
    email: str
    password: str


@router.post('/verify')
async def users_verify(
    body: VerifyRequest,
    _: bool = Depends(verify_api_key),
):
    """Verify credentials. Returns user record on success, 401 on failure.

    Used by the Next.js /api/voice/login proxy in place of the previous
    DEEK_USERS-env parsing. Same return shape: {email, name, role}.
    """
    user = user_store.verify_password(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail='invalid credentials')
    return {'ok': True, **user}


# ── /me/password — self-service change ───────────────────────────────


class ChangePasswordRequest(BaseModel):
    email: str = Field(..., description='Email of the user changing their own password')
    old_password: str
    new_password: str


@router.post('/me/password')
async def users_change_password(
    body: ChangePasswordRequest,
    _: bool = Depends(verify_api_key),
):
    """Change password (user self-service). Verifies the old password
    before accepting the new one. The proxy passes session.email as
    body.email so the user can only change their own password."""
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail='new password must be at least 8 characters',
        )
    ok = user_store.change_password(
        body.email,
        body.old_password,
        body.new_password,
        by_email=body.email,
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail='current password incorrect (or user not found)',
        )
    return {'ok': True}


# ── /admin/reset ─────────────────────────────────────────────────────


class AdminResetRequest(BaseModel):
    target_email: str
    new_password: str
    by_email: str = Field(..., description='Email of the admin doing the reset (audit log)')


@router.post('/admin/reset')
async def users_admin_reset(
    body: AdminResetRequest,
    _: bool = Depends(verify_api_key),
):
    """Admin reset — sets a new password without verifying the old one.
    Authorisation (ADMIN role check) is enforced at the proxy layer."""
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail='new password must be at least 8 characters',
        )
    ok = user_store.admin_reset_password(
        body.target_email,
        body.new_password,
        by_email=body.by_email,
    )
    if not ok:
        raise HTTPException(status_code=404, detail='user not found')
    return {'ok': True}


# ── /list ────────────────────────────────────────────────────────────


@router.get('/list')
async def users_list(_: bool = Depends(verify_api_key)):
    """List all users — for the /admin/users page. Excludes bcrypt_hash."""
    return {'users': user_store.list_users()}
