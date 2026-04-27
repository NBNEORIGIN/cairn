# Jo's Pip v0 — Handover

**Date:** 2026-04-27 (revised after Toby's "no Telegram, app-only" call + OpenRouter key)
**Status:** Infrastructure staged on nbne1. PWA brief surface still to build before v0 is launchable.
**Companion docs:**
- `briefs/jo-pip-v0-spec.md` — deployment + boundaries
- `briefs/jo-pip-mobile-design.md` — UX + interaction design

---

## v0 architecture (revised)

Jo will not see "Telegram" in the user-facing UX. Mention of bots, @BotFather, or chat tokens is a churn risk for her specifically. Architecture revised accordingly:

- **No Telegram.** Drop the polling daemon, drop the bot setup, drop the chat_id pairing flow.
- **PWA installed to her home screen** is the app she opens daily.
- **Email is purely a notification** — "your brief is ready, open Rex." She does not reply via email; she opens the PWA.
- **OpenRouter is the only cloud tier** (Toby's Rex-specific OpenRouter key, DeepSeek-via-OpenRouter for general work, Claude-via-OpenRouter for opus tier). No direct Anthropic/OpenAI/DeepSeek keys.
- **All inbound traffic via Tailscale to `jo.nbne.local`.** No public ingress whatsoever.

---

## What's staged

| | |
|---|---|
| Capacity check on nbne1 | ✅ green |
| `/opt/nbne/jo-pip/` directory + permissions | ✅ |
| Deek repo cloned at `/opt/nbne/jo-pip-src/` | ✅ commit `dd7261eb` |
| `docker-compose.yml` (revised, 2 services: db + api, no poller) | ✅ |
| `.env` with fresh `POSTGRES_PASSWORD` + `DEEK_API_KEY` + Toby's `OPENROUTER_API_KEY` | ✅ — `OPENROUTER_MODEL` defaults to `deepseek/deepseek-chat` |
| Image built (`jo-pip-deek:latest`) | ✅ |
| Nginx vhost on `100.125.120.1:80` | ✅ live |
| Jo project profile (`projects/jo/config.json` + `identity.md`) | ✅ in master + cloned to nbne1 |

---

## What remains — three layers

### Layer 1: 5-minute manual steps (Toby)

Only one placeholder left in `.env`:

```bash
ssh toby@192.168.1.228
sudo -e /opt/nbne/jo-pip/.env
```

Fill from Hetzner's `.env`:
- `SMTP_HOST` (probably `smtp.eu.postmarkapp.com` or `smtp.ionos.co.uk`)
- `SMTP_USER`
- `SMTP_PASS`

Then bring up the stack:

```bash
cd /opt/nbne/jo-pip
docker compose up -d
docker compose ps
docker compose logs -f --tail 50
```

Apply migrations (auto on API boot — verify):

```bash
docker exec -w /app -e PYTHONPATH=/app jo-pip-api python -c "
from core.memory.migrations import apply_migrations
import json
print(json.dumps(apply_migrations(), indent=2, default=str))
"
```

Test the email send path (this lands a brief in Jo's inbox):

```bash
docker exec -w /app -e PYTHONPATH=/app jo-pip-api \
  python scripts/send_memory_brief.py --user jo@nbnesigns.com --force --verbose
```

If she gets an email titled "Deek morning brief — 2026-04-27" — outbound is working. **But she can't reply yet** until the PWA brief surface is built (Layer 2).

### Layer 2: PWA brief surface (1-2 days engineering)

This is the v0-launchable deliverable that hasn't been built yet. Per `jo-pip-mobile-design.md` §4.2, the v0 PWA needs:

1. **Today's brief at the top.** If unanswered, four questions inline with reply boxes per question.
2. **Reply box per question.** Plain prose; conversational normaliser maps to right Q. Same backend as email replies.
3. **Recent chat history** (read-only).
4. **Memory search** (single search box, returns matching chunks).
5. **Recent memory write events** (chronological list).
6. **Persistent confidentiality banner**: `🔒 Rex — jo.nbne.local`.

Implementation note from the mobile-design doc: reuse existing `/voice` PWA components (chat surface, message list, voice input). The work is configuration + theming + brief-surface integration, not a new codebase.

**What's in the existing `/voice` PWA today:** chat-stream surface for real-time chat. Doesn't currently render the morning brief or have per-question reply boxes. Those need to be built.

**Where the work lands:** `web/src/app/voice/` — add a new route `/voice/brief` (or similar) that fetches the latest unanswered brief from `/api/deek/brief/today` (new endpoint), renders the question list, accepts inline replies, posts back to a new `/api/deek/brief/reply` endpoint that runs the same parser path Hetzner uses for email-channel replies.

This is real work. **Best handed off as its own implementation brief**, not bundled into "v0 staging." Estimate ~2 days from a fresh CC session.

### Layer 3: PWA installation on Jo's phone (5 min when Toby + Jo can sit together)

After Layer 2 is live:

1. Confirm Tailscale is installed on Jo's phone + signed into the NBNE tailnet. Toby helps her install if needed (App Store / Play Store search "Tailscale", sign in with NBNE account). Jo's device added to the tailnet ACL allowlist for nbne1.
2. Jo opens Safari (iOS) or Chrome (Android), goes to `https://nbne1.<tailnet-name>.ts.net/voice/brief`.
3. Browser menu → "Add to Home Screen". Jo names the icon "Rex". The icon now lives on her home screen and opens directly into the PWA when tapped.
4. Optional: enable MagicDNS so `jo.nbne.local` resolves cleanly. Set in Tailscale admin console.

She's done. From then on: tap Rex icon → see today's brief if unanswered → reply inline.

---

## What changed vs the previous handover

The previous handover (committed earlier today) had Telegram as the primary surface. That's been dropped:

| Was | Now |
|---|---|
| `TELEGRAM_BOT_TOKEN` placeholder in `.env` | removed |
| `jo-pip-poller` container | removed |
| Jo creates Rex via @BotFather | removed |
| Telegram chat-id pairing | removed |
| Email channel disabled by default | now the only channel |
| Telegram polling driver as a daily process | not used in Jo's deployment (still in codebase for Toby's instance) |

The Telegram polling code (`core/channels/telegram_polling.py`, PR #55) stays in the Deek codebase — it's Pip-tenant-agnostic and might be useful for a future user. It's just not wired into Jo's deployment.

---

## Cost expectations

OpenRouter routing default is `deepseek/deepseek-chat` which is roughly **$0.27 / $1.10 per million input/output tokens** (cheaper than direct DeepSeek but with the convenience tax). At Jo's expected usage (~50K tokens/day from briefs + ad-hoc questions), monthly cost is probably **£1-3**.

Claude-via-OpenRouter for opus-tier work is more expensive (~$15 / $75 per million tokens) but rarely triggered — opus_keywords on Jo's profile gate that escalation to specific high-stakes content (decisions, contracts, performance issues).

---

## Open architecture decisions (deferred to v0.5)

These don't block v0 launch but warrant attention before user count grows:

1. **Voice in the PWA.** Currently in `/voice`; not yet integrated with the brief surface. Jo might want voice-to-text for ad-hoc captures. v0.5 work.
2. **Web push notifications.** Currently the morning brief lands as email. A "your brief is ready" push notification on her installed PWA would be lower-friction. Requires VAPID keys + service-worker push handler. v0.5 work.
3. **Memory audit + bulk delete UI.** v0.5 — Jo asks for it eventually.

---

## Honest status summary

What I've shipped this session:

- All deployment infrastructure on nbne1: containers, secrets, network, image
- Codebase additions: Telegram polling driver (committed but not used by Jo), Jo's project profile, identity.md
- Three docs: v0 spec, mobile design, this handover
- The role-revisions in `user_profiles.yaml` (your edit) — Jo: `operations_hr_finance`, Ivan: `production_tech`

What I have not shipped:

- The PWA brief surface (Layer 2 above). It's the user-facing deliverable that turns Rex from "infra running" into "Jo can use this." Estimated 1-2 days fresh-session engineering.
- The role-specific question builders (`hr_pulse`, `finance_check`, `d2c_observation` for Jo; `production_quality`, `equipment_health`, `technical_solve` for Ivan). YAML declares them; code doesn't yet handle them — they fall back to open-ended templates.
- Existing brief replies migration from NBNE-Deek → Rex.

The Layer 2 PWA work is the meaningful next chunk. I can do it in a follow-up turn or hand to a fresh session — your call.
