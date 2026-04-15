# Beacon — Cairn Agent Core Context
# Version: 1.0
# Updated: 2026-04-15

## What this is

Beacon is NBNE's Google Ads conversion upload + campaign observability
service. It connects tenant Google Ads accounts via OAuth, pulls campaign
state on a schedule, and uploads offline click conversions attributed from
Phloe / CRM / Manufacture events.

Phase 1 is operational wiring: live API integration against the NBNE MCC,
scheduled jobs, and a Cairn context endpoint. Attribution logic is built
on top later.

## Repository

- GitHub: NBNEORIGIN/beacon (private)
- Local: D:\beacon
- Stack: Django 5.2 + DRF, PostgreSQL, google-ads 30.0.0 (API v20), Celery + Redis
- Deploy: TBC — dev only as of 2026-04-15

## Non-negotiable rules

1. Every query that touches ads data MUST filter by `tenant` — Beacon is
   multi-tenant on the same schema.
2. Refresh tokens are encrypted via `core.crypto.encrypt()`. Never log,
   never serialise, never store plaintext. Decrypt in-process only.
3. All money values flow through `core.money.Money`. Never print or
   compare raw micros outside that class.
4. Never access another module's database directly. Talk to Phloe / CRM /
   Manufacture over HTTP, not via shared tables.
5. Manager (MCC) accounts never receive conversion uploads or appear as
   reporting targets — only sub-accounts. Heartbeat and sync must filter
   on `GoogleAdsAccount.is_manager = false`.

## Google Ads reality (as of 2026-04-15)

- google-ads pinned at 30.0.0 → API version **v20**
- MCC customer id: `2141262231` (manager, no campaigns of its own)
- Live sub-account: `2028631064` — runs "Shop Signage in Northumberland"
  and "Personalised Memorials"
- `list_accessible_customers()` returns both IDs
- Developer token, client_id, client_secret, encryption key in
  `backend/config/settings/` (see `.env`, never commit)

## App layout

```
backend/
  ads/            Google Ads integration — client, models, OAuth, management cmds
  attribution/    Conversion attribution logic (Phase 2+)
  cairn_app/      /api/cairn/context endpoint for Cairn business brain
  config/         Django settings, urls, celery config
  core/           crypto, money, shared utilities
  tenants/        BeaconTenant model, Phloe client, tenant sync
  webhooks/       Inbound webhook receivers (Phloe / CRM / Manufacture)
```

## Database tables (beacon_ prefix)

- `beacon_tenant` — one row per NBNE business using Beacon
- `beacon_google_ads_account` — OAuth-connected Ads account per tenant
- `beacon_campaign_cache` — latest campaign snapshot from Google Ads
- `beacon_job_run` — scheduled job heartbeat + outcome (Outcome 2 of Phase 1)

## Management commands

- `beacon_test_ads_connection --tenant <uuid>` — verify OAuth works
- `beacon_smoke_campaigns --customer-id <id>` — print live campaign data
  with 7-day metrics (Outcome 1 of Phase 1)
- `beacon_sync_tenants` — pull tenant list from Phloe (stub)
- `beacon_upload_conversions` — process attribution queue and upload

## Scheduler

Celery + django-celery-beat. Gated behind `BEACON_SCHEDULER_ENABLED`.
Phase 1 jobs:
- `beacon_sync_tenants` — every 15 min
- `beacon_upload_conversions` — every 15 min
- `beacon_smoke_campaigns` for customer 2028631064 — every hour
  (heartbeat + cache refresh)

Every scheduled run writes one row to `beacon_job_run`. Cairn context
endpoint surfaces `last_success` / `last_failure` per job.

## Cairn context contract

`GET /api/cairn/context` returns:
- tenants — count + status
- accounts — connected / expired / revoked / error breakdown
- campaigns — last cache refresh timestamp per account
- scheduler — last success / failure timestamp per job (added in Phase 1)
- health — overall status derived from the above

## Decision log

- **D-001** — Django + DRF chosen over FastAPI for tenant-auth + admin parity
  with Phloe
- **D-002** — Refresh tokens encrypted at rest via Fernet (core.crypto)
- **D-003** — Money helper mandatory; no raw micros outside it
- **D-004** — google-ads 30.0.0 (v20) — latest stable as of session
- **D-005** — MCC account 2141262231 confirmed manager; campaigns live on
  sub-account 2028631064
- **D-006** — `list_campaigns()` uses two GAQL queries merged in Python:
  (1) `FROM campaign` selecting `campaign_budget.amount_micros` for all
  campaigns, (2) `FROM campaign WHERE segments.date DURING LAST_7_DAYS`
  for metrics, aggregated per campaign.id. Single-query with the
  segments.date filter rejected because it drops zero-activity campaigns
  from the cache. Verified live against sub-account 2028631064 on
  2026-04-15 — 4 campaigns cached. Known Phase 2 gap: cache rows scope
  to the auth account (MCC), not the queried customer_id.
- **D-007** — Celery + declarative `CELERY_BEAT_SCHEDULE` dict chosen
  over django-celery-beat DatabaseScheduler, APScheduler, and cron.
  Celery: Phloe precedent, already in requirements, one scheduler per
  module is the NBNE convention. Dict over DB-backed scheduler: Phase 1
  schedules are few and code-reviewable; swap to DatabaseScheduler if
  operators later need no-deploy schedule edits. MCC filter enforced by
  pinning `customer_id` in the schedule entry (not via a runtime
  `is_manager=false` filter in the command) so the non-MCC contract is
  visible at a glance and the smoke command remains ad-hoc-callable
  against any customer_id for debugging. Beat+worker live cycle NOT
  verified in this session — Redis not running in dev; deploy env must
  run `celery -A config beat` and `celery -A config worker` for one
  15-min cycle to close the acceptance loop.

## Out of scope for Phase 1

- Attribution model (Phase 2)
- Phloe tenant API endpoint contract (separate session in phloe module)
- Webhook secret configs (separate sessions in CRM / Manufacture modules)
- Admin UI auth hardening
