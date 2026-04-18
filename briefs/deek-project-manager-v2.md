# DEEK ACTIVE PROJECT MANAGER — BUILD BRIEF v2

**Supersedes:** original "DEEK ACTIVE PROJECT MANAGER — IMPLEMENTATION BRIEF"
**Date:** 2026-04-19
**Context:** Staff have crossed the adoption threshold. This brief gives Deek the capability to actively manage tasks, assign work, chase progress, and brief the team — not just answer on demand.

The model is a knowledgeable colleague who happens to know everything about every active job, every machine, every order, every deadline, and will proactively tell you what needs doing rather than wait to be asked.

---

## What's already in place (do not rebuild)

- `deek_tasks` table with `id, assignee, content, status, source, location, created_by, created_at, due_at, completed_at` — from the voice PWA work
- `POST /api/deek/tasks`, `GET /api/deek/tasks?assignee=X&status=Y`, `PATCH /api/deek/tasks/{id}` — CRUD already works
- `GET /api/deek/ambient?location=X` — morning-number + panels for workshop/office/home
- Module federation snapshots in `claw_code_chunks` (chunk_type='module_snapshot') refreshed every 15 min from Manufacture, CRM, Ledger, Render, Phloe
- Self-contained Deek login with `DEEK_USERS` env + `deek.session` JWT cookie
- Voice PWA at `deek.nbnesigns.co.uk/voice` with Chat + Voice modes, HAL/Constellation faces, streaming TTS, wiki-commit
- APScheduler-capable — the API already has startup hooks (see `api/main.py` lifespan)

---

## What "active project manager" means in practice

Deek should be able to:

1. **Assign tasks** — "Ben, SAVILLE batch x48 on ROLF today, priority 1"
2. **Chase progress** — "DONALD reorder flagged 3 days ago, not done"
3. **Morning briefing** — daily summary per staff member appropriate to role
4. **Escalate blockers** — flag to Toby/Jo when overdue / stuck
5. **Answer status queries** — "Deek, where are we with the Miter order?"
6. **Log completions** — staff tell Deek "done", Deek updates task state

---

## Data sources Deek uses

All via canonical Deek endpoints. No direct module DB access.

| Source | Endpoint | What Deek gets |
|---|---|---|
| Manufacture | `GET /api/deek/context` (via module federation, pre-polled) | Make list, machine status, stock alerts |
| Ledger | (same, via federation) | Cash, margins, revenue by channel |
| CRM | (same) | Pipeline, follow-ups due, open quotes |
| Email triage | `cairn_intel.email_triage` table (already populated) | Classified inbound |

Primary mechanism: read the already-embedded federation snapshots from `claw_code_chunks` — same pattern the ambient endpoints already use. No new polling. No module DB access.

Consumer module endpoints continue to accept both `/api/deek/*` (primary) and `/api/cairn/*` (legacy alias) during the rename window.

---

## Staff profiles

New table `deek_staff_profile` keyed on email. Authoritative person data (id, name, email, role) lives in the CRM's NextAuth user table — we do NOT duplicate it. The profile holds Deek-specific preferences.

```sql
CREATE TABLE deek_staff_profile (
    email VARCHAR(200) PRIMARY KEY,
    display_name VARCHAR(100),
    role_tag VARCHAR(30),                   -- production | dispatch | tech | admin | director
    briefings_enabled BOOLEAN NOT NULL DEFAULT true,
    briefing_time TIME NOT NULL DEFAULT '07:30',
    active_days VARCHAR(20) NOT NULL DEFAULT 'mon,tue,wed,thu,fri',
    quiet_start TIME NOT NULL DEFAULT '22:00',
    quiet_end TIME NOT NULL DEFAULT '06:30',
    preferred_voice VARCHAR(200),           -- SpeechSynthesis voice name
    preferred_face VARCHAR(20),             -- 'eye' | 'net'
    notes TEXT,                              -- free-text overrides / context
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

Initial seed via env or admin UI:

| Email | role_tag | notes |
|---|---|---|
| toby@nbnesigns.com | director | cross-business overview, blockers, decisions needed |
| jo@nbnesigns.com | director | operations, client relationships, cash position |
| ben@nbnesigns.com | production | make list, machine assignments, batch priorities |
| gabby@nbnesigns.com | dispatch | dispatch queue, labels, packing |
| ivan@nbnesigns.com | tech | machine maintenance flags, CNC job queue |
| sanna@nbnesigns.com | admin | email triage, quote follow-ups, supplier comms |

Editable via `/admin/staff` page in the web UI. Directors only.

---

## Extend the existing `deek_tasks` table

Do NOT build a parallel table. Add missing columns via an `ALTER TABLE` migration that runs on API startup (same defensive-migration pattern as other Deek tables):

```sql
ALTER TABLE deek_tasks ADD COLUMN IF NOT EXISTS title VARCHAR(200);
ALTER TABLE deek_tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(10);   -- low | medium | high | critical
ALTER TABLE deek_tasks ADD COLUMN IF NOT EXISTS context TEXT;
ALTER TABLE deek_tasks ADD COLUMN IF NOT EXISTS linked_module VARCHAR(40);
ALTER TABLE deek_tasks ADD COLUMN IF NOT EXISTS linked_ref VARCHAR(200);
```

`linked_module:linked_ref` format: `manufacture:M-2119`, `crm:project_id:abc123`, `ledger:account:wise_nbne_main`.

The existing `content` column stays (for voice-captured free-text notes). New fields are optional — a voice "remind Ben to check DONALD" still works with just content. A PM-style task has title + priority + linked_ref.

---

## Feature 1 — On-demand briefing FIRST

Ship this before any scheduling or push.

```
GET /api/deek/briefing?user=<email>
```

Returns a markdown briefing tailored to the user's `role_tag`. Uses the same federation snapshots the ambient endpoint already parses, plus the user's open tasks from `deek_tasks`.

Response:
```json
{
  "user": "toby@nbnesigns.com",
  "role_tag": "director",
  "generated_at": "2026-04-19T07:32:01Z",
  "briefing_md": "## Deek's morning read — 19 April 2026\n\n..."
}
```

Every briefing starts with **"Deek's morning read —"** so it's clearly Deek's assessment, not management instruction. Every claim is traceable to the underlying snapshot (same snapshots `/api/deek/ambient` uses).

Per-role template:

- **production (Ben):** top 3 make-list items, machine status, stock reorder flags affecting them, their open tasks
- **dispatch (Gabby):** today's ready-to-ship, label printer status, any pack blockers
- **tech (Ivan):** machine maintenance flags, CNC queue, any equipment alerts from Manufacture
- **admin (Sanna):** email triage count (last 24h), overdue follow-ups, open supplier comms
- **director (Toby/Jo):** cash position, follow-ups overdue with £ value, pipeline delta, any critical-priority tasks, any 24h+ escalations

Under the hood, each role's briefing is a small deterministic function — it pulls the right snapshot fields + tasks, formats them, and optionally calls local Qwen 7B to add a single summary sentence at the top. No big prompt engineering. The data IS the briefing.

**PWA:** `/voice` gains a "Briefing" tab alongside Chat + Voice. Opens straight to your briefing. Tapping a task opens the task. Refresh button re-fetches.

---

## Feature 2 — Scheduled briefing generation (non-push)

Daily at 06:45 (just before the earliest briefing time), a scheduled job runs:

1. For each staff profile where `briefings_enabled = true` and today's weekday is in `active_days`
2. Call the briefing function to generate markdown
3. Insert a row into `deek_pending_briefings`:
   ```sql
   CREATE TABLE deek_pending_briefings (
       id SERIAL PRIMARY KEY,
       email VARCHAR(200) NOT NULL,
       generated_at TIMESTAMPTZ DEFAULT NOW(),
       briefing_md TEXT NOT NULL,
       seen_at TIMESTAMPTZ,
       dismissed_at TIMESTAMPTZ
   );
   ```
4. When the user opens the PWA, the header shows a **badge** (small dot + count) if they have unseen briefings. Tapping the briefing tab loads the latest; marking seen sets `seen_at = NOW()`.

No push notifications in Phase 1. Badge + user opens app = delivery. Cheapest to ship, iOS-friendly, zero VAPID keys, zero service-worker push setup.

APScheduler integrates into the existing `api/main.py` lifespan handler (same place the module federation poll loop is kicked off).

---

## Feature 3 — Task delivery in the briefing

Each briefing ends with the user's open tasks for today, rendered as a list. A "Mark done" action next to each task calls `PATCH /api/deek/tasks/{id}` with `status: "done"`.

No voice task completion in Phase 1. That's Phase 2 (disambiguation is hard).

---

## Constraints (unchanged from v1, tightened wording)

- Deek never sends email on behalf of staff without explicit confirmation.
- Deek never modifies consumer module state. Stock level corrections, production order updates, CRM project edits — Deek creates a _task_ for a human; the human actions it in the relevant module's UI.
- Any autonomous actions Deek takes require a **delegation** record (see Future Work — bounded delegation). Not in Phase 1.
- All task assignments visible to Toby + Jo regardless of assignee (acceptable trade-off given team size of 6).
- Every briefing is prefixed "**Deek's morning read —**" and lists the source snapshot timestamp so the user knows how fresh the data is.
- Briefings and tasks are capped by the existing `DEEK_VOICE_DAILY_LIMIT` if they trigger LLM calls. Most briefing content is deterministic formatting, not LLM — the LLM cost should be trivial.

---

## What's NOT in Phase 1

- Web Push / APNs / service-worker push notifications → Phase 1.5
- Voice task completion ("Hey Deek, SAVILLE done") → Phase 2
- Proactive escalation (Deek pinging Toby when cash drops) → Phase 2
- Bounded delegation ("Deek, handle DONALD reorders") → Phase 3
- Retrospective analysis ("how did we do vs target this month?") → Phase 3

---

## Observability (Phase 1 must-have)

Cheap logging now so Phase 3 can analyse later. Add to existing `deek_task_events` OR extend the voice telemetry table:

```sql
CREATE TABLE IF NOT EXISTS deek_task_events (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES deek_tasks(id) ON DELETE CASCADE,
    event VARCHAR(30) NOT NULL,         -- created | assigned | status_change | note_added | completed
    actor VARCHAR(200),                  -- email or 'deek'
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Every briefing generation also logs to a simple `deek_briefing_events` table so we can see: did Ben open his briefing? When? For how long? This is "did the feature work" telemetry, not surveillance.

---

## When Deek is wrong

Every briefing has a "mark incorrect" link. Clicking it:
- Flags the briefing in `deek_pending_briefings.incorrect_reason TEXT`
- Optionally the user types what was wrong
- Directors can scan these weekly and adjust the briefing template

Without a correction loop, confidence erodes silently.

---

## Implementation order — Phase 1 (1 week target)

1. **Schema** — `ALTER deek_tasks` + create `deek_staff_profile` + create `deek_pending_briefings` + create `deek_task_events`. Seed staff profiles via env. (1 h)
2. **Briefing function** — per-role deterministic builder + one LLM sentence at top. `GET /api/deek/briefing?user=X`. (1 day)
3. **Admin UI** — `/admin/staff` page for directors to edit profiles (briefing time, active days, enabled flag, voice/face prefs). (half day)
4. **PWA Briefing tab** — third tab alongside Chat + Voice. Shows latest briefing, task list with mark-done. Badge on header when unseen. (1 day)
5. **Scheduler** — APScheduler job at 06:45 generates briefings + inserts into `deek_pending_briefings`. (half day)
6. **Task event logging** — instrument the existing task endpoints. (1 h)
7. **Deploy + ship to Toby/Jo for one week of daily use.** Iterate on the content based on what's missing or wrong.

---

## Critical files to modify

- `api/routes/ambient.py` — extend with briefing + staff profile endpoints
- `api/main.py` — APScheduler startup hook for the daily job
- `web/src/app/voice/page.tsx` — add Briefing tab to mode toggle
- `web/src/components/voice/BriefingView.tsx` (new)
- `web/src/app/admin/staff/page.tsx` (new)

---

## Verification

1. `curl https://deek.nbnesigns.co.uk/api/deek/briefing?user=toby@nbnesigns.com -H "X-API-Key:..."` returns a markdown briefing with cash position, follow-ups, pipeline
2. Visit `/admin/staff` as Toby — see 6 profiles, edit one, confirm persistence
3. Create a task via `POST /api/deek/tasks` with `assignee: ben@nbnesigns.com`, then `GET /briefing?user=ben@nbnesigns.com` and see that task in the tasks section
4. Manually trigger the scheduler (admin endpoint), confirm a row appears in `deek_pending_briefings` for each enabled staff member
5. Open `/voice` → Briefing tab → latest briefing shows, badge disappears after view, mark-done on a task moves it to `completed`
6. Mark a briefing as incorrect, check that `incorrect_reason` is populated

## Success metric for Phase 1

After 5 working days of daily use, Toby + Jo report:
- Briefings actively change at least one decision per week each
- At least 3 staff-member tasks are created via Deek in that week (not just by Toby)
- Zero "Deek was wrong and I couldn't flag it" reports

If not met, iterate on the briefing content before building Phase 2.
