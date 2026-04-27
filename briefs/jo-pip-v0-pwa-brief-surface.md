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
2. **One reply box per question.** Plain prose. On submit, post to a new `/api/deek/brief/reply` endpoint that runs the **same conversational normaliser path** Hetzner uses for email-channel replies (`core/brief/reply_normaliser.py` — local Qwen via Ollama, JSON output). Do NOT build a parallel parser.
3. **Recent chat history** (read-only, last ~20 turns).
4. **Memory search** (single search box → matching chunks, reuse existing `/retrieve` or `/api/wiki/search`).
5. **Recent memory write events** (chronological list — last 20 writes from `cairn_memory_writes` or equivalent log).
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
- Runs each answer through the existing reply normaliser (same code path as email replies — find it via `grep -r "reply_normaliser\|process_brief_reply" core/ api/`)
- Writes to memory the same way email replies do. Provenance: `source="pwa_brief_reply"`, `channel="pwa"`.
- Returns: `{ "ok": true, "memory_writes": [...], "normalised": {...} }`

**Critical:** reuse the existing parser. The whole point is that PWA replies and email replies converge on one normalisation path. Do not duplicate logic.

---

## Frontend work

Land in `web/src/app/voice/`:

- New route `web/src/app/voice/brief/page.tsx`
- Reuse existing components from `web/src/components/voice/` (chat surface, message list, auth) — configuration + theming, not a new codebase
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
