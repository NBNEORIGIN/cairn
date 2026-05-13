"""
/api/voice/inbox — the active-PM inbox surface.

Lists Deek-drafted replies awaiting Toby's review, lets him edit
inline, stage to sales@ for manual send, or reject without sending.

Auth: same `getServerSession` pattern as other /api/voice/* routes
(checked at the Next.js proxy layer; this endpoint is internal).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from typing import Optional

from api.middleware.auth import verify_api_key


router = APIRouter(
    prefix='/api/voice/inbox',
    tags=['Voice Inbox'],
    dependencies=[Depends(verify_api_key)],
)


# ── List + detail ──────────────────────────────────────────────────────────

@router.get('')
async def list_inbox(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project_id: Optional[str] = Query(None),
    include_reviewed: bool = Query(False),
):
    """Card list for the PWA inbox view.

    Default = unreviewed-only; pass ``include_reviewed=true`` to see
    historical drafts (for the "what did I action last week?" view).
    Optional ``project_id`` filter for the per-project pending-replies
    panel.
    """
    from core.triage.inbox import list_pending_drafts
    rows = list_pending_drafts(
        limit=limit, offset=offset,
        project_id=project_id, include_reviewed=include_reviewed,
    )
    return {'count': len(rows), 'rows': rows}


@router.get('/{triage_id}')
async def get_inbox_item(triage_id: int):
    """Detail panel — full original email + full draft + match audit."""
    from core.triage.inbox import get_pending_draft
    row = get_pending_draft(triage_id)
    if not row:
        raise HTTPException(404, 'triage row not found')
    return row


# ── Actions ────────────────────────────────────────────────────────────────

class _EditBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    draft_reply: str


@router.post('/{triage_id}/edit')
async def edit_inbox_item(triage_id: int, payload: _EditBody):
    """Inline edit. Doesn't mark reviewed — Toby can iterate before
    staging. The edit is tagged in the draft_model audit string so
    you can see machine vs human authorship in the row history."""
    from core.triage.inbox import update_draft_text
    result = update_draft_text(triage_id, payload.draft_reply)
    if not result.get('ok'):
        raise HTTPException(400, result.get('error', 'edit failed'))
    return result


class _StageBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    staged_by: Optional[str] = None
    dry_run: bool = False


@router.post('/{triage_id}/stage')
async def stage_inbox_item(triage_id: int, payload: _StageBody):
    """Send the drafted reply to sales@ for manual review-and-send.

    On success the triage row is marked reviewed with
    ``review_action='staged_to_sales'`` so the card drops out of the
    pending list. ``dry_run=true`` returns the proposed email
    contents without sending — used by the PWA preview tab so Toby
    can see EXACTLY what would land in sales@ before committing.
    """
    from core.triage.inbox import stage_to_sales
    result = stage_to_sales(
        triage_id,
        staged_by=payload.staged_by or '',
        dry_run=bool(payload.dry_run),
    )
    if not result.get('ok'):
        raise HTTPException(400, result.get('error', 'stage failed'))
    return result


class _RejectBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    rejected_by: Optional[str] = None
    reason: Optional[str] = None


@router.post('/{triage_id}/reject')
async def reject_inbox_item(triage_id: int, payload: _RejectBody):
    """Mark reviewed without staging anything. Use this when the
    drafted reply is structurally wrong (wrong product, wrong tone,
    wrong template) and you don't want it sent in any form. The
    reason persists in review_notes so retrieval/training picks it
    up."""
    from core.triage.inbox import reject_draft
    result = reject_draft(
        triage_id,
        rejected_by=payload.rejected_by or '',
        reason=payload.reason or '',
    )
    if not result.get('ok'):
        raise HTTPException(404, result.get('error', 'reject failed'))
    return result
