# Jo's Pip — PWA Brief Surface (Layer 2)

The `/voice/brief` route on Jo's Pip — a single-screen daily app where today's morning brief renders inline with reply boxes per question, plus memory search, recent chat, and recent memory writes.

Built 2026-04-27, commit `bed7896`. Deployed to nbne1 once the jo-pip image is rebuilt (see `briefs/jo-pip-v0-layer3-deploy.md`).

## Architecture summary

PWA replies converge on the **same `apply_reply()` path** the email channel uses — there is no parallel parser.

```
Jo types reply ─→ /voice/brief BriefCard
                       │
                       ↓ POST /api/deek/brief/reply
                       │ (Next.js proxy, gates on session.email)
                       ↓
              api/routes/brief_pwa.py
                       │
                       │ for each {question_id, text}:
                       │   _classify(text) → (verdict, correction)
                       │   ParsedAnswer(...)
                       ↓
              core.brief.replies.apply_reply(conn, ParsedReply)
                       │ (mutates schemas, writes new memory chunks
                       │  via _write_toby_memory, returns audit summary)
                       ↓
              core.brief.replies.store_response(...)
                       │ (idempotent insert in memory_brief_responses)
                       ↓
              applied_summary['channel'] = 'pwa'
              applied_summary['source']  = 'pwa_brief_reply'
```

## Backend endpoints (additive — `/api/deek/brief/*`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/deek/brief/today?user=<email>` | Latest brief in last 36h. 404 if none. Returns `{brief_id, date, subject, questions, answered, answers}`. |
| POST | `/api/deek/brief/reply` | Body `{brief_id, answers:[{question_id, text}]}`. Runs through `_classify` → `ParsedAnswer` → `apply_reply`. Idempotent via existing `already_applied()` SHA check. Stamps `channel='pwa'` for provenance. |
| GET | `/api/deek/brief/memory/recent?user=<email>&limit=20` | Last N chunks written via `memory/brief-reply/*` so the PWA write feed stays scoped (does not show generic code-chunk indexing). |

## Frontend layout (`web/src/app/voice/brief/`)

| Element | Component | Source |
|---|---|---|
| 🔒 Sticky `Rex — <host>` | `ConfidentialityBanner` | window.location.host |
| Today's brief + reply boxes | `BriefCard` | `/api/deek/brief/today` |
| Recent chat (~20 turns) | `RecentChatHistory` | reuses `/api/voice/sessions?user=<email>&limit=20` |
| Memory search | `MemorySearch` | proxies `/api/wiki/search` |
| Recent memory writes | `MemoryWriteFeed` | `/api/deek/brief/memory/recent` |

## Why the LLM normaliser is skipped

The email channel needs `core/brief/conversational.py` (local Qwen via Ollama) because email replies arrive as free-form prose with no per-question delimiters. The PWA already binds each text input to a specific `question_id`, so the mapping question→answer is unambiguous. `_classify(text)` is enough to detect TRUE/YES verdicts; everything else is treated as a correction. Same memory-write semantics, much cheaper.

## Why a new route, not extending `BriefingView`

`web/src/components/voice/BriefingView.tsx` is a different concept — Deek's "morning read" with task list + dream candidates + briefing markdown. It's not the memory-brief reply system. Both can coexist; tabs and tasks live at `/voice`, brief reply lives at `/voice/brief`. Jo's home-screen icon points at `/voice/brief`; Toby's at `/voice`.

## Tenant scoping

`DEEK_USERS` is a shared cookie on Toby's instance. Both `/today` and `/memory/recent` filter by `session.email` at the Next.js proxy layer — neither user sees the other's brief. On Jo's isolated jo-pip Postgres, this is moot (DB-level isolation), but the proxy filters defensively anyway.

## Memory writes

`_write_toby_memory()` (the helper invoked from `apply_reply`) hardcodes `project_id='deek'` and `file_path='memory/brief-reply/<sha16>'`. On jo-pip's isolated DB this writes into the local `claw_code_chunks` and stays in Jo's instance. The MemoryWriteFeed filters on `file_path LIKE 'memory/brief-reply/%'` so it shows brief-derived writes, not the `wiki` chunk_type freshness writes that the broader Cairn Protocol writeback emits.

## Layer 3 — deploy + install

See `briefs/jo-pip-v0-layer3-deploy.md` for the rebuild steps + Tailscale + Add-to-Home-Screen flow. Until that runs, `/voice/brief` is master-only — the production `jo-pip-deek:latest` image still ships pre-Layer 2 code.

## Tests

`tests/test_brief_pwa.py` — 18 tests, helpers + endpoint shape via FastAPI `TestClient` with a fake DB connection. The DB-mutating apply path is exercised live on Hetzner; the existing `tests/memory/test_brief_replies.py` (49 tests) covers `apply_reply` end-to-end.
