# Jo's Pip v0 — Layer 3: Deploy + Install

**For:** Toby + Jo (5–15 min sit-together)
**Status:** Layer 1 ✅ (infra staged), Layer 2 ✅ (PWA built — commit `bed7896`). This is the last step.
**Pre-req:** Layer 1's Toby-only manual steps must be done — the SMTP secrets in `/opt/nbne/jo-pip/.env` filled in, stack up, brief email landing in Jo's inbox.

---

## Step 1 — Pull + rebuild the jo-pip image (Toby, 3 min)

```bash
ssh toby@192.168.1.228
cd /opt/nbne/jo-pip-src
git pull origin master         # picks up Layer 2 — PWA brief surface
cd /opt/nbne/jo-pip
docker compose build api       # rebuild jo-pip-deek:latest with new code
docker compose up -d --force-recreate api
docker compose logs -f --tail 50 api
```

Wait until you see `Application startup complete` and the migrations log
clean, then Ctrl-C the logs.

Smoke from the host:

```bash
curl -s http://localhost/health | jq .status      # via nginx
curl -s -X GET "http://localhost/api/deek/brief/today?user=jo@nbnesigns.com" \
  -H "X-API-Key: $(grep '^DEEK_API_KEY=' .env | cut -d= -f2)" | jq .
```

Expected: `{ "brief_id": "...", "questions": [...], "answered": false, ... }`
or `{ "detail": "no_brief_today" }` if no brief generated yet today —
both prove the route is live.

---

## Step 2 — Tailscale on Jo's phone (Jo + Toby, 5 min)

1. Jo opens the App Store (iOS) or Play Store (Android), searches **Tailscale**, installs.
2. Jo opens Tailscale → "Sign in with Microsoft / Google" → uses her **NBNE account** (`jo@nbnesigns.com`).
3. Toby opens the Tailscale admin console (`login.tailscale.com/admin/machines`), confirms Jo's device shows up. Adds it to the ACL allowlist for `100.125.120.1` (nbne1) if a tag-based rule isn't already covering it.
4. Test from Jo's phone Safari/Chrome: visit `http://jo.nbne.local` — should resolve to nbne1's nginx and show the Deek voice login.

If `jo.nbne.local` doesn't resolve, fall back to the tailnet IP
`http://100.125.120.1` until MagicDNS catches up.

---

## Step 3 — Sign in + add to home screen (Jo, 2 min)

1. Jo navigates to `http://jo.nbne.local/voice/brief` (the brief surface, not `/voice` — that's the chat/voice interface for ad-hoc).
2. The page redirects to `/voice/login`. Jo signs in with her email + the password Toby set in `DEEK_USERS`.
3. Lands back on `/voice/brief` — sees the confidentiality strip, today's brief if one exists, memory search, recent writes.
4. **Add to Home Screen:**
   - **iOS Safari:** Share button (square + arrow up) → "Add to Home Screen" → name it **Rex** → Add.
   - **Android Chrome:** ⋮ menu → "Add to Home screen" → name it **Rex** → Add.
5. Tap the Rex icon on her home screen — opens directly into `/voice/brief`. Done.

---

## Step 4 — First-day check (Toby + Jo, 5 min next morning)

After Jo's first morning brief lands (~07:32 UTC):

1. Jo opens Rex from her home screen.
2. The brief should be there with reply boxes per question.
3. She types one short answer per question, taps **Send replies**.
4. Page flips to the "Brief sent — replied" state with her answers shown.
5. Scroll down → her reply should appear in **Recent memory writes** within a few seconds (entry like `Jo open-ended reflection: ...`).
6. Tomorrow morning's brief should be informed by today's writes.

If anything in steps 1–5 doesn't behave as described, Toby checks the
api container logs:

```bash
docker compose logs --tail 200 api | grep -i 'brief\|reply'
```

---

## Out of scope (v0.5)

- Voice in the brief surface — Jo's chat surface is `/voice`, separate URL for now
- Web push notifications — requires VAPID + service worker, deferred
- Memory bulk-delete UI — Jo can delete via per-item flag if/when she wants it
- Migration of Jo's existing brief replies from NBNE-Deek into Rex — separate SQL fixup, run manually after Layer 3 is bedded in

---

## If something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `/voice/brief` returns 502 | Backend route not loaded (stale image) | Rebuild + recreate api container per Step 1 |
| `404 no_brief_today` even though Jo got the email | Brief generated under a different `user_email` than the one in DEEK_USERS | Check `SELECT user_email, generated_at FROM memory_brief_runs ORDER BY generated_at DESC LIMIT 5;` and align case/spelling |
| Reply submits but no memory write appears | `apply_reply` failed silently inside the per-answer try block | Tail api logs for `[brief-reply]` warnings |
| Login loop — `/voice/brief` keeps redirecting to `/voice/login` | DEEK_USERS env not loaded by the api container | `docker compose exec api env \| grep DEEK_USERS` — restart with `--env-file .env` if empty |

---

When Layer 3 is bedded in, update `briefs/jo-pip-v0-handover.md` to mark v0 launched and mothball this brief.
