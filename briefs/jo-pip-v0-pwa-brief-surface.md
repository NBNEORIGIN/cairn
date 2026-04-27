# Jo's Pip v0 — PWA Brief Surface (Layer 2)

**For:** fresh Claude Code session against the Deek repo (`D:\claw\`)
**Estimate:** 1–2 days
**Status:** infrastructure live on nbne1; this is the last piece blocking v0 launch.

---

## Read first (in order)

1. `CLAUDE.md` — Deek agent scope
2. `briefs/jo-pip-v0-handover.md` — what's already staged + the three-layer plan (you are Layer 2)
3. `briefs/jo-pip-v0-spec.md` — deployment + boundaries (hostname, Tailscale, no public ingress)
4. `briefs/jo-pip-mobile-design.md` §4.2 — the v0 PWA feature set you're building

Then look at:
- `web/src/app/voice/page.tsx` and the components under `web/src/components/voice/` — the existing PWA you're extending
- `api/routes/` — where the new endpoints land (look at how email replies are processed today; you'll reuse that parser path)
- `core/brief/` — brief generation + reply normaliser

---

## What you're building

A new route `/voice/brief` on the existing `/voice` PWA that gives Jo a single-screen daily surface:

1. **Today's brief at the top.** If unanswered, render the four questions inline with one reply box per question. If already answered, show a "Brief sent — replied" state and the captured answers below.
2. **One reply box per question.** Plain prose. On submit, post to a new `/api/deek/brief/reply` endpoint that converges on the **same `apply_reply()` path** the email channel uses (`core/brief/replies.py` — `apply_reply()` mutates schemas, writes new memory chunks, stores the response row). Each PWA answer is bound to a `question_id`, so the LLM normaliser (`core/brief/conversational.py`, local Qwen via Ollama) is **not** required — build a `ParsedAnswer` per submitted answer using the existing `_classify()` helper for verdict mapping (TRUE/YES/etc), then hand the `ParsedReply` to `apply_reply()`. Do NOT build a parallel parser.
3. **Recent chat history** (read-only, last ~20 turns).
4. **Memory search** (single search box → matching chunks, proxy to `GET /api/wiki/search?q=...&top_k=10` — the canonical wiki/memory full-text + embedding hybrid endpoint per session-start ritual).
5. **Recent memory write events** (chronological list — last 20 entries from `claw_code_chunks` filtered to `chunk_type IN ('memory', 'wiki')` AND `salience_signals->>'via' = 'memory_brief_reply'` OR `file_path LIKE 'memory/brief-reply/%'` ORDER BY `indexed_at DESC`. The `cairn_memory_writes` table does NOT exist — `claw_code_chunks` is the canonical store; see your auto-memory entry "Cairn embedding schema").
6. **Persistent confidentiality banner** at the top: `🔒 Rex — jo.nbne.local`. Always visible.

This is Jo's daily app. She taps the icon, sees today's brief, replies inline, done. Email is a notification only — never a reply channel for her.

---

## New backend endpoints

Both under `/api/deek/brief/` (additive, no consumer breaks):

### `GET /api/deek/brief/today`
- Auth: existing voice/PWA session auth (`web/src/lib/auth.ts`)
- Returns: latest brief for the authenticated user (Jo) including:
  ```json
  {
    "brief_id": "...",
    "date": "2026-04-27",
    "subject": "Rex morning brief — 2026-04-27",
    "questions": [
      {"id": "q1", "category": "hr_pulse", "text": "..."},
      ...
    ],
    "answered": false,
    "answers": []  // populated if answered
  }
  ```
- If no brief exists for today, return 404 (UI shows "No brief yet today").

### `POST /api/deek/brief/reply`
- Body: `{ "brief_id": "...", "answers": [{"question_id": "q1", "text": "..."}, ...] }`
- For each `{question_id, text}` in the body:
  - Look up the question in `memory_brief_runs.questions` to recover its `category` and `provenance` dict
  - Build a `ParsedAnswer` via `from core.brief.replies import _classify, ParsedAnswer; verdict, correction = _classify(text)`
  - Append to a single `ParsedReply(run_date, user_email)`
- Call `apply_reply(conn, parsed_reply)` (same function the email path uses) — this mutates schemas, writes memory chunks, returns the audit summary
- Call `store_response(conn, run_id, raw_body=json.dumps(answers), parsed_reply, applied_summary)` so the response is recorded idempotently in `memory_brief_responses`
- Stamp `applied_summary['channel'] = 'pwa'` before storing so PWA-vs-email provenance is queryable later
- Returns: `{ "ok": true, "applied_summary": {...} }`

**Critical:** reuse `apply_reply()`. The whole point is that PWA replies and email replies converge on one apply path with identical memory-write semantics. Do not duplicate the schema-mutation or chunk-insertion logic.

**Tenant scoping:** the auth session gives you `session.email`. Both `GET /today` and the memory search must filter `user_email = session.email` so Toby cannot see Jo's brief and vice versa (DEEK_USERS is a shared cookie env). On Jo's isolated jo-pip DB this is moot, but on Toby's shared instance it matters.

**Project key for memory writes:** the existing `_write_toby_memory()` hardcodes `project_id='deek'` ([core/brief/replies.py:681](core/brief/replies.py:681)). On jo-pip's isolated DB that's fine — the DB itself provides the isolation. On a multi-tenant shared instance you'd want per-user scoping; out of scope for v0.

---

## Frontend work

Land in `web/src/app/voice/`:

- New route `web/src/app/voice/brief/page.tsx`
- Note: existing `BriefingView.tsx` is a *different* concept (Deek's morning read = tasks + dream candidates + briefing markdown). It is NOT the memory-brief reply system. Build alongside, don't extend.
- Reuse auth + general styling from existing voice components — but the brief-reply surface is its own component tree.
- New components as needed:
  - `BriefCard.tsx` — renders the question list with inline reply boxes
  - `MemorySearch.tsx` — search box + result list
  - `MemoryWriteFeed.tsx` — chronological write events
  - `ConfidentialityBanner.tsx` — persistent `🔒 Rex — jo.nbne.local` strip
- Proxy routes under `web/src/app/api/deek/brief/` for the two new endpoints
- Mode: this is the **default landing page** for Jo's PWA. `/voice/brief` should be where the home-screen icon points (per `briefs/jo-pip-v0-spec.md` Layer 3 step 2).

---

## What's already on nbne1 (do not redo)

- `/opt/nbne/jo-pip/` directory + permissions
- `docker-compose.yml` (db + api, no poller)
- `.env` complete except SMTP_HOST/USER/PASS placeholders Toby fills manually
- `jo-pip-deek:latest` image built
- Nginx vhost on `100.125.120.1:80` for `jo.nbne.local`
- Jo's project profile (`projects/jo/config.json` + `identity.md`)
- OpenRouter key wired (cloud tier = DeepSeek-via-OpenRouter by default; Claude-via-OpenRouter for opus)

Your work is purely **codebase additions** (new endpoints + new PWA route). No nbne1 server changes needed until you're ready to deploy. Build/test against local Deek first; deploy by rebuilding `jo-pip-deek:latest` on nbne1 once endpoints are green.

---

## Out of scope for this session

- Voice in the brief surface (v0.5)
- Web push notifications (v0.5 — requires VAPID + service worker)
- Memory bulk-delete UI (v0.5)
- Role-specific question builders (`hr_pulse`, `finance_check`, etc.) — YAML declares them, `core/brief/questions.py` falls back to open-ended templates. Separate session.
- Migration of Jo's existing brief replies from NBNE-Deek → Rex (separate SQL fixup)
- Tailscale ACL + PWA install on Jo's phone (Layer 3 — Toby + Jo together)

---

## Definition of done

1. `GET /api/deek/brief/today` returns today's brief for Jo (or 404)
2. `POST /api/deek/brief/reply` round-trips through the same normaliser email replies use, writes to memory with `channel="pwa"` provenance
3. `/voice/brief` renders all six elements from `jo-pip-mobile-design.md` §4.2
4. Replies submitted in the PWA appear in memory + are visible in subsequent retrievals — verify via `retrieve_chat_history` or the memory search box you just built
5. Tests: shape tests for both new endpoints; component tests for `BriefCard` reply submission
6. Deployed to nbne1: rebuild image, `docker compose up -d`, smoke from a tailnet device hitting `http://jo.nbne.local/voice/brief`

When done: update `briefs/jo-pip-v0-handover.md` to mark Layer 2 ✅ and write a Layer 3 prompt for Toby.

---

## Confirm before starting

- Deek API reachable: `GET http://localhost:8765/health`
- Pull memory: `retrieve_codebase_context(query="brief reply normaliser pwa", project="deek", limit=5)` and `retrieve_chat_history(query="jo pip pwa brief surface", project="deek", limit=5)`
- If anything in the staged infra above is unclear, read the handover doc again before writing code
