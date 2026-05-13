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


# A separate router exposed at /api/cairn/notifications so CRM has
# a stable namespace to consume (matches the rest of the /api/cairn/*
# CRM-facing surface). All endpoints are read-only counts/lists; the
# action endpoints stay on /api/voice/inbox.
crm_router = APIRouter(
    prefix='/api/cairn/notifications',
    tags=['CRM Notifications'],
    dependencies=[Depends(verify_api_key)],
)


@crm_router.get('/unread_count')
async def unread_count_global(project_id: Optional[str] = Query(None)):
    """Badge count for the CRM header (or a per-project chip).

    Returns the count of pending drafts (draft_reply present,
    reviewed_at IS NULL). Optional ``project_id`` filter for the
    per-project chip on a CRM project page.
    """
    from core.triage.inbox import _conn
    sql = (
        "SELECT COUNT(*) FROM cairn_intel.email_triage "
        "WHERE draft_reply IS NOT NULL AND draft_reply <> '' "
        "AND reviewed_at IS NULL"
    )
    params: list = []
    if project_id:
        sql += " AND project_id = %s"
        params.append(project_id)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            count = cur.fetchone()[0]
    return {'unread_count': int(count), 'project_id': project_id}


@crm_router.get('/pending')
async def pending_list(
    limit: int = Query(50, ge=1, le=200),
    project_id: Optional[str] = Query(None),
):
    """Same data as /api/voice/inbox but namespaced under /api/cairn/*
    so CRM has a stable contract.

    Read-only — for actions and detail, CRM calls the matching
    ``/api/cairn/notifications/{id}/{...}`` endpoints below (which
    are also under the open X-API-Key namespace; the original
    ``/api/voice/inbox/*`` route is blocked by the PWA's
    session-cookie nginx rule)."""
    from core.triage.inbox import list_pending_drafts
    rows = list_pending_drafts(
        limit=limit, offset=0,
        project_id=project_id, include_reviewed=False,
    )
    return {'count': len(rows), 'rows': rows}


@crm_router.get('/learning/stats')
async def crm_learning_stats():
    """Verification surface for the inbox learning pipeline.

    Toby's question: "how do I check Deek is actually learning?"
    Honest answer: writes work, reads don't (yet). This endpoint
    surfaces the counts that prove writes ARE happening so the gap
    can be measured rather than guessed at.

    Returns counts for the four claimed pipeline components plus a
    breakdown of recent review actions, so the dashboard can show
    "feedback recorded" alongside the existing learning artefacts.
    """
    from core.triage.inbox import _conn, _crm_conn
    out: dict = {}

    # 1. RAG — chunks embedded into claw_code_chunks
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM claw_code_chunks WHERE chunk_type='email'"
                )
                out['email_chunks'] = int(cur.fetchone()[0])
                cur.execute(
                    "SELECT COUNT(*) FROM claw_code_chunks WHERE chunk_type='wiki'"
                )
                out['wiki_chunks'] = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM claw_code_chunks")
                out['total_chunks'] = int(cur.fetchone()[0])
                # Best-effort last-write timestamp — column name varies
                # by schema version (created_at vs indexed_at vs ts).
                for col in ('indexed_at', 'created_at', 'ts'):
                    try:
                        cur.execute(
                            f"SELECT MAX({col}) FROM claw_code_chunks "
                            f"WHERE chunk_type IN ('email','wiki')"
                        )
                        last = cur.fetchone()[0]
                        out['last_chunk_at'] = last.isoformat() if last else None
                        break
                    except Exception:
                        conn.rollback()
                        continue
    except Exception as exc:
        out['embeddings_error'] = str(exc)

    # 2. BM25 — persistent tsvector index check (we don't have one;
    #    the dashboard should flag this honestly)
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) FROM pg_indexes
                        WHERE tablename IN ('claw_code_chunks','email_triage')
                          AND indexdef LIKE '%tsvector%'"""
                )
                out['tsvector_indexes'] = int(cur.fetchone()[0])
    except Exception as exc:
        out['bm25_error'] = str(exc)

    # 3. Feedback — review_action counts (write-only path, but worth
    #    showing the volume so Toby can see his corrections landing)
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COALESCE(review_action, 'pending') AS action,
                              COUNT(*)
                         FROM cairn_intel.email_triage
                        GROUP BY 1
                        ORDER BY 2 DESC"""
                )
                out['review_action_totals'] = [
                    {'action': r[0], 'count': int(r[1])} for r in cur.fetchall()
                ]
                cur.execute(
                    """SELECT COALESCE(review_action,'pending') AS action,
                              COUNT(*)
                         FROM cairn_intel.email_triage
                        WHERE reviewed_at >= NOW() - INTERVAL '7 days'
                           OR (reviewed_at IS NULL AND processed_at >= NOW() - INTERVAL '7 days')
                        GROUP BY 1
                        ORDER BY 2 DESC"""
                )
                out['review_action_7d'] = [
                    {'action': r[0], 'count': int(r[1])} for r in cur.fetchall()
                ]
                cur.execute(
                    """SELECT COUNT(*) FROM cairn_intel.email_triage
                        WHERE draft_reply IS NOT NULL"""
                )
                out['drafts_written_total'] = int(cur.fetchone()[0])

                # Phase 1 learning-loop counter: how many emails has the
                # triage_runner skipped in the last 7 days because Toby
                # previously marked the sender spam/internal/domain?
                # If this number grows over the coming week, the loop
                # is closed for the spam-skip case.
                cur.execute(
                    """SELECT COUNT(*) FROM cairn_intel.email_triage
                        WHERE review_action = 'auto_skipped'
                          AND reviewed_at >= NOW() - INTERVAL '7 days'"""
                )
                out['auto_skipped_7d'] = int(cur.fetchone()[0])
                cur.execute(
                    """SELECT COUNT(*) FROM cairn_intel.email_triage
                        WHERE review_action = 'auto_skipped'"""
                )
                out['auto_skipped_total'] = int(cur.fetchone()[0])
                # Per-reason breakdown for the dashboard.
                cur.execute(
                    """SELECT
                          CASE
                            WHEN review_notes LIKE 'auto_skipped: internal_domain%%' THEN 'internal_domain'
                            WHEN review_notes LIKE 'auto_skipped: sender_marked_spam%%' THEN 'sender_marked_spam'
                            WHEN review_notes LIKE 'auto_skipped: sender_marked_internal%%' THEN 'sender_marked_internal'
                            ELSE 'other'
                          END AS reason,
                          COUNT(*)
                         FROM cairn_intel.email_triage
                        WHERE review_action = 'auto_skipped'
                          AND reviewed_at >= NOW() - INTERVAL '7 days'
                        GROUP BY 1 ORDER BY 2 DESC"""
                )
                out['auto_skipped_by_reason_7d'] = [
                    {'reason': r[0], 'count': int(r[1])} for r in cur.fetchall()
                ]

                # Phase 2 counter: how many reassignments has Toby done
                # in the last 7 days, and how many distinct senders does
                # the matcher now have boost rules for? The "reassigns"
                # number is the input; the "senders_with_boost" number
                # is the matcher's *learned* state — that's the one that
                # proves Phase 2 is reading feedback back.
                cur.execute(
                    """SELECT COUNT(*) FROM cairn_intel.email_triage
                        WHERE review_notes LIKE 'reassigned to %%'
                          AND reviewed_at >= NOW() - INTERVAL '7 days'"""
                )
                out['reassigns_7d'] = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT LOWER(email_sender))
                      FROM cairn_intel.email_triage
                     WHERE review_notes LIKE 'reassigned to %%'
                       AND reviewed_at >= NOW() - INTERVAL '365 days'
                    """
                )
                out['senders_with_matcher_boost'] = int(cur.fetchone()[0])
    except Exception as exc:
        out['feedback_error'] = str(exc)

    # Read-back consumption flags. Phase 1 (skip rules) and Phase 2
    # (matcher feedback) are live; reranker (Phase 3) and persistent
    # BM25 (Phase 4) remain unwired.
    out['feedback_consumed_by_skip_rules'] = True
    out['feedback_consumed_by_matcher'] = True
    out['feedback_consumed_by_reranker'] = False
    out['bm25_persisted'] = (out.get('tsvector_indexes') or 0) > 0

    return out


@crm_router.get('/{triage_id}')
async def crm_get_inbox_item(triage_id: int):
    """Detail panel data for the CRM inbox view. Same payload as
    ``GET /api/voice/inbox/{id}`` but reachable with the shared
    X-API-Key (the PWA route is session-gated by nginx)."""
    from core.triage.inbox import get_pending_draft
    row = get_pending_draft(triage_id)
    if not row:
        raise HTTPException(404, 'triage row not found')
    return row


class _CrmEditBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    draft_reply: str
    edited_by: Optional[str] = None


@crm_router.post('/{triage_id}/edit')
async def crm_edit_inbox_item(triage_id: int, payload: _CrmEditBody):
    """Save Toby's edits to the draft. Doesn't mark reviewed — same
    semantics as the PWA's /api/voice/inbox/{id}/edit."""
    from core.triage.inbox import update_draft_text
    result = update_draft_text(triage_id, payload.draft_reply)
    if not result.get('ok'):
        raise HTTPException(400, result.get('error', 'edit failed'))
    return result


class _CrmRejectBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    rejected_by: Optional[str] = None
    reason: Optional[str] = None


@crm_router.post('/{triage_id}/reject')
async def crm_reject_inbox_item(triage_id: int, payload: _CrmRejectBody):
    """Reject a draft (wrong tone / wrong template / wrong product).
    Reason persists in review_notes so the reranker learns."""
    from core.triage.inbox import reject_draft
    result = reject_draft(
        triage_id,
        rejected_by=payload.rejected_by or '',
        reason=payload.reason or '',
    )
    if not result.get('ok'):
        raise HTTPException(404, result.get('error', 'reject failed'))
    return result


class _CrmSpamBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    marked_by: Optional[str] = None
    reason: Optional[str] = None


@crm_router.post('/{triage_id}/spam')
async def crm_mark_spam(triage_id: int, payload: _CrmSpamBody):
    """Mark a triaged email as spam so Deek learns not to draft for
    similar senders/topics. Mirrors reject but records
    ``review_action='spam'`` which the reranker treats as a strong
    negative signal (and the classifier picks up on rebuild)."""
    from core.triage.inbox import mark_as_spam
    result = mark_as_spam(
        triage_id,
        marked_by=payload.marked_by or '',
        reason=payload.reason or '',
    )
    if not result.get('ok'):
        raise HTTPException(404, result.get('error', 'spam mark failed'))
    return result


class _CrmArchiveBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    archived_by: Optional[str] = None
    reason: Optional[str] = None


@crm_router.post('/{triage_id}/archive')
async def crm_archive(triage_id: int, payload: _CrmArchiveBody):
    """Mark a draft archived — Toby's already actioned it (copied to
    clipboard, pasted into sales@, sent manually) and wants it out of
    the pending queue. Neutral signal, not a learning event."""
    from core.triage.inbox import archive_draft
    result = archive_draft(
        triage_id,
        archived_by=payload.archived_by or '',
        reason=payload.reason or '',
    )
    if not result.get('ok'):
        raise HTTPException(404, result.get('error', 'archive failed'))
    return result


class _CrmInternalBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    marked_by: Optional[str] = None
    reason: Optional[str] = None


@crm_router.post('/{triage_id}/internal')
async def crm_mark_internal(triage_id: int, payload: _CrmInternalBody):
    """Mark a triaged email as internal staff comms — not client, not
    spam. Deek shouldn't draft client-style replies for chatter
    between people at @nbnesigns.com or @nbnesigns.co.uk. Persists
    ``review_action='internal_communication'`` for the matcher to
    learn from."""
    from core.triage.inbox import mark_as_internal
    result = mark_as_internal(
        triage_id,
        marked_by=payload.marked_by or '',
        reason=payload.reason or '',
    )
    if not result.get('ok'):
        raise HTTPException(404, result.get('error', 'internal mark failed'))
    return result


class _CrmReassignBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    project_id: Optional[str] = None
    reassigned_by: Optional[str] = None
    reason: Optional[str] = None


@crm_router.post('/{triage_id}/reassign')
async def crm_reassign_project(triage_id: int, payload: _CrmReassignBody):
    """Override Deek's project match. Used when Deek guessed wrong (or
    didn't guess at all). Persists the correction in review_notes so
    the matcher learns. ``project_id=None`` clears the association."""
    from core.triage.inbox import reassign_to_project
    result = reassign_to_project(
        triage_id,
        new_project_id=payload.project_id,
        reassigned_by=payload.reassigned_by or '',
        reason=payload.reason or '',
    )
    if not result.get('ok'):
        raise HTTPException(404, result.get('error', 'reassign failed'))
    return result


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
