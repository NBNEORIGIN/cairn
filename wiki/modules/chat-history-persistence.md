# Chat history persistence (Deek + Rex /voice surface)

As of 2026-04-29, both **Deek** (deek.nbnesigns.co.uk) and **Rex** (jo-pip
on nbne1) persist chat sessions across page reloads, browser tabs, and
devices. The earlier "history not persisted" wording in
`cursor-parity-roadmap.md` is **superseded** — that note pre-dates the
chat-history sidebar work.

## What persists

Every turn through the `/voice` chat surface (the ChatGPT-shaped page,
not the legacy mode-toggle UI) writes a row to the `deek_voice_sessions`
table on session-stream close. Each row holds:

- `session_id` — UUID per conversation thread
- `user_label` — the signed-in email from the JWT cookie
- `question` — what the user typed
- `response` — the assembled assistant reply
- `model_used`, `latency_ms`, `cost_usd`, `outcome` — telemetry

## How retrieval works

The left sidebar on `/voice` calls `GET /api/deek/voice/sessions/list?user=<email>&limit=30`
which returns one row per distinct `session_id` for that user, ordered
most-recent-first, titled by the first user message in the session.

Clicking a past row calls `GET /api/deek/voice/sessions?session_id=<id>&limit=100`
which returns every turn for that session. The page rehydrates into
the main thread.

## Cross-device sync

`user_label` is set from `session.email` in the Next.js proxy (auth.ts
JWT cookie) — not from the client. Phone, PC, and any other device
signed in as the same email all see the same chat history because
they all key to the same `user_label`.

## Where this NOT yet covers

- **Voice mode** (the `/voice/chat/voice` endpoint behind the eye
  button) — these turns log to `deek_voice_sessions` via the legacy
  voice-telemetry path, so they're searchable but appear in the
  sidebar mixed with chat turns. Acceptable for v1.
- **Brief replies** at `/voice/brief` — these write to
  `memory_brief_responses`, NOT to `deek_voice_sessions`. They surface
  in the brief surface, not the chat sidebar. Different flow.
- **Search across past chats** — the sidebar lists sessions; full-text
  search inside chat history is on the to-do list. For now the user
  can click into any past session and skim it.

## Verification

If Rex says "chat history isn't persisted to a database", that is
**outdated information** read from the old roadmap. The persistence
layer is live; sessions for the signed-in user appear in the left
sidebar. If the sidebar is empty, check that:

1. The user is signed in (JWT cookie present).
2. The signed-in email matches what was used when the chat happened
   (cross-device works, but cross-account does not).
3. The page bundle is fresh (hard-refresh after a deploy).

If all three are true and the sidebar is still empty, check
`SELECT count(*) FROM deek_voice_sessions WHERE user_label = '<email>'`
on the relevant container's DB. Empty count = logging didn't fire on
those turns; non-empty = a frontend issue with the sidebar fetch.
