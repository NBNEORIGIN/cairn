"""Memory Brief — PWA reply surface (Layer 2 of Jo's Pip v0).

Companion to:
  * core/brief/composer.py + replies.py (email channel — outbound brief
    + inbox-poll parser)
  * core/brief/telegram_delivery.py + api/routes/telegram.py (Telegram
    channel — Toby's primary daily surface)

Endpoints (additive — no consumer breaks):

  GET  /api/deek/brief/today?user=<email>
       Returns the most recent memory_brief_runs row for the user
       within the last 36h, plus its answered/answers state. 404 if
       no brief generated.

  POST /api/deek/brief/reply
       Body: { brief_id, answers: [{question_id, text}, ...] }
       Converges on the same apply_reply() path the email parser
       uses — same memory-write semantics, same audit row in
       memory_brief_responses. PWA-channel provenance stamped via
       applied_summary['channel'] = 'pwa'.

The PWA already binds each reply to a question_id, so the LLM
normaliser (core/brief/conversational.py) is NOT invoked here.
We only need to map text → verdict via the existing _classify()
helper, build a ParsedReply, and call apply_reply().

Tenant scoping note: ``user`` parameter must match the authenticated
session — that filter is enforced at the Next.js proxy layer
(web/src/app/api/deek/brief/*), which reads session.email and
forwards as a query param. This endpoint trusts the API-key bearer
exactly as every other /api/deek/* endpoint does.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from api.middleware.auth import verify_api_key

log = logging.getLogger(__name__)
router = APIRouter(prefix='/brief', tags=['Memory Brief PWA'])


def _connect():
    import psycopg2
    db_url = os.getenv('DATABASE_URL', '')
    if not db_url:
        return None
    try:
        return psycopg2.connect(db_url, connect_timeout=5)
    except Exception as exc:
        log.warning('[brief-pwa] db connect failed: %s', exc)
        return None


def _question_id(idx_one_based: int) -> str:
    return f'q{idx_one_based}'


def _parse_question_id(qid: str) -> int | None:
    """'q3' -> 3. None on malformed input."""
    s = (qid or '').strip().lower()
    if not s.startswith('q'):
        return None
    try:
        n = int(s[1:])
        return n if n >= 1 else None
    except ValueError:
        return None


def _normalise_questions(raw: Any) -> list[dict]:
    """memory_brief_runs.questions is JSONB; psycopg2 may return it as
    list, str, or dict-of-list depending on driver. Normalise to a
    plain list of question dicts."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return [q for q in raw if isinstance(q, dict)]
    return []


# ── GET /today ───────────────────────────────────────────────────────


@router.get('/today')
async def brief_today(
    user: str = Query(..., min_length=3, description='Recipient email'),
    _: bool = Depends(verify_api_key),
) -> JSONResponse:
    """Latest brief for ``user`` (within the last 36h) plus its
    answered/answers state.

    Returns 404 if there is no brief in the window — UI shows
    "No brief yet today".
    """
    conn = _connect()
    if conn is None:
        raise HTTPException(status_code=503, detail='database_unreachable')
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id::text, generated_at, subject, questions
                     FROM memory_brief_runs
                    WHERE user_email = %s
                      AND delivery_status IN ('sent', 'pending', 'dry_run')
                      AND generated_at > NOW() - INTERVAL '36 hours'
                    ORDER BY generated_at DESC
                    LIMIT 1""",
                (user,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail='no_brief_today')
            brief_id, generated_at, subject, questions_raw = row

            # Look up any responses already stored for this run (PWA
            # or email — both land in memory_brief_responses).
            cur.execute(
                """SELECT parsed_answers, applied_summary, received_at
                     FROM memory_brief_responses
                    WHERE run_id = %s::uuid
                    ORDER BY received_at DESC
                    LIMIT 1""",
                (brief_id,),
            )
            response_row = cur.fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    questions_list = _normalise_questions(questions_raw)
    questions_out: list[dict] = []
    for i, q in enumerate(questions_list, 1):
        questions_out.append({
            'id': _question_id(i),
            'category': str(q.get('category') or 'open_ended'),
            'text': str(q.get('prompt') or ''),
            'reply_format': str(q.get('reply_format') or ''),
        })

    answered = response_row is not None
    answers_out: list[dict] = []
    if response_row:
        parsed_raw, applied_raw, received_at = response_row
        parsed = parsed_raw if isinstance(parsed_raw, dict) else (
            json.loads(parsed_raw) if isinstance(parsed_raw, str) else {}
        )
        for a in (parsed.get('answers') or []):
            qn = a.get('q_number')
            answers_out.append({
                'question_id': _question_id(int(qn)) if qn else None,
                'category': str(a.get('category') or ''),
                'verdict': str(a.get('verdict') or ''),
                'correction_text': str(a.get('correction_text') or ''),
            })

    return JSONResponse({
        'brief_id': brief_id,
        'date': generated_at.date().isoformat() if generated_at else None,
        'subject': subject or '',
        'questions': questions_out,
        'answered': answered,
        'answers': answers_out,
    })


# ── POST /reply ──────────────────────────────────────────────────────


@router.post('/reply')
async def brief_reply(
    payload: dict = Body(...),
    _: bool = Depends(verify_api_key),
) -> JSONResponse:
    """Apply PWA-submitted answers via the same path email replies use.

    Body shape:
      {
        "brief_id": "<uuid>",
        "answers": [
          {"question_id": "q1", "text": "..."},
          ...
        ]
      }

    The PWA binds each text to a specific question, so this endpoint
    skips the LLM normaliser and goes straight to _classify() →
    ParsedAnswer → apply_reply(). Same memory-write semantics as
    email; ``applied_summary['channel'] = 'pwa'`` distinguishes the
    provenance for later querying.
    """
    brief_id = (payload or {}).get('brief_id') or ''
    answers_in = (payload or {}).get('answers') or []
    if not brief_id:
        raise HTTPException(status_code=400, detail='brief_id_required')
    if not isinstance(answers_in, list) or not answers_in:
        raise HTTPException(status_code=400, detail='answers_required')

    # Lazy imports — keep the module loadable even if core.brief is
    # broken (e.g. missing optional deps in a partial install).
    from core.brief.replies import (
        ParsedAnswer,
        ParsedReply,
        _classify,
        already_applied,
        apply_reply,
        store_response,
    )

    conn = _connect()
    if conn is None:
        raise HTTPException(status_code=503, detail='database_unreachable')
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT user_email, generated_at, questions
                     FROM memory_brief_runs
                    WHERE id = %s::uuid
                    LIMIT 1""",
                (brief_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='brief_not_found')
        user_email, generated_at, questions_raw = row
        questions_list = _normalise_questions(questions_raw)
        if not questions_list:
            raise HTTPException(
                status_code=500, detail='brief_has_no_questions',
            )

        run_date = generated_at.date() if generated_at else date.today()

        # Build ParsedAnswer list, skipping malformed inputs but
        # surfacing the parse_notes for the audit row.
        parse_notes: list[str] = []
        parsed_answers: list[ParsedAnswer] = []
        for ans in answers_in:
            if not isinstance(ans, dict):
                parse_notes.append('answer not a dict; skipped')
                continue
            qid = str(ans.get('question_id') or '').strip()
            text = str(ans.get('text') or '').strip()
            q_idx = _parse_question_id(qid)
            if q_idx is None or q_idx > len(questions_list):
                parse_notes.append(f'unknown question_id={qid!r}; skipped')
                continue
            q = questions_list[q_idx - 1]
            category = str(q.get('category') or 'open_ended')
            verdict, correction = _classify(text)
            parsed_answers.append(ParsedAnswer(
                q_number=q_idx,
                category=category,
                raw_text=text,
                verdict=verdict,
                correction_text=correction,
            ))

        if not parsed_answers:
            raise HTTPException(
                status_code=400,
                detail='no_answers_recognised',
            )

        parsed_reply = ParsedReply(
            run_date=run_date,
            user_email=user_email,
            answers=parsed_answers,
            parse_notes=parse_notes,
        )

        # Idempotency: if this exact JSON body has been seen for this
        # run, return the prior summary instead of double-applying.
        raw_body = json.dumps(
            {'channel': 'pwa', 'answers': answers_in},
            sort_keys=True,
        )
        if already_applied(conn, brief_id, raw_body):
            conn.commit()
            return JSONResponse({
                'ok': True,
                'idempotent': True,
                'applied_summary': {
                    'note': 'this exact reply body was already applied',
                    'channel': 'pwa',
                },
            })

        applied_summary = apply_reply(conn, parsed_reply)
        applied_summary['channel'] = 'pwa'
        applied_summary['source'] = 'pwa_brief_reply'

        response_id = store_response(
            conn, brief_id, raw_body, parsed_reply, applied_summary,
        )
        conn.commit()
    except HTTPException:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        log.exception('[brief-pwa] reply apply failed: %s', exc)
        raise HTTPException(status_code=500, detail=f'apply_failed: {type(exc).__name__}')
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return JSONResponse({
        'ok': True,
        'idempotent': False,
        'response_id': response_id,
        'applied_summary': applied_summary,
    })


# ── GET /memory/recent (for the PWA's memory-write feed) ─────────────


@router.get('/memory/recent')
async def brief_memory_recent(
    user: str = Query(..., min_length=3, description='Recipient email'),
    limit: int = Query(default=20, ge=1, le=100),
    _: bool = Depends(verify_api_key),
) -> JSONResponse:
    """Recent memory chunks written by this user's brief replies.

    Filters claw_code_chunks for chunks created via the brief-reply
    pipeline (file_path LIKE 'memory/brief-reply/%') so the PWA's
    "recent memory write events" panel stays scoped to brief writes
    and doesn't get drowned in code-chunk indexing churn.
    """
    conn = _connect()
    if conn is None:
        raise HTTPException(status_code=503, detail='database_unreachable')
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, chunk_name, chunk_content, indexed_at,
                          salience, salience_signals
                     FROM claw_code_chunks
                    WHERE chunk_type = 'memory'
                      AND file_path LIKE 'memory/brief-reply/%%'
                      AND (
                            chunk_content ILIKE %s
                         OR salience_signals->>'user_email' = %s
                          )
                    ORDER BY indexed_at DESC
                    LIMIT %s""",
                (f'%{user}%', user, limit),
            )
            rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items: list[dict] = []
    for row in rows:
        rid, chunk_name, content, indexed_at, salience, signals = row
        snippet = (content or '')
        if len(snippet) > 240:
            snippet = snippet[:237] + '…'
        items.append({
            'id': int(rid),
            'name': chunk_name or '',
            'snippet': snippet,
            'indexed_at': indexed_at.isoformat() if indexed_at else None,
            'salience': float(salience) if salience is not None else None,
            'via': (signals or {}).get('via') if isinstance(signals, dict) else None,
        })

    return JSONResponse({'items': items, 'count': len(items)})
