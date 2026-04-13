# Amazon Listing Intelligence — Session 1 Prompt
# Paste this into a fresh Claude Code chat instance

Read `CAIRN_PROTOCOL.md`, `CLAUDE.md`, `CAIRN_MODULES.md`, and `docs/cairn/CAIRN_AMAZON_LISTINGS_CC_PROMPT.md` before starting. This session covers Phases 0–2 of that brief, modified by Toby's feedback below.

## What this session delivers

Phases 0, 1, and 2 from the Amazon listings brief. The irreversible work (Phase 5 nuke) is reserved for Session 2.

- **Phase 0 (auth):** Already done — all three regions authenticate. This session just enables NA/FE in the scheduler and runs the ads profile discovery fix.
- **Phase 1 (initial backfill plumbing):** Extend the existing inventory sync to capture full listing content via per-ASIN Catalog Items API calls — titles, bullets, descriptions, image URLs, variation relationships. Store in new `ami_listing_content` table (not the broken `ami_listing_snapshots`). Embed listing text via nomic-embed-text into pgvector.
- **Phase 2 (notification infrastructure):** AWS SQS setup, boto3 integration, SP-API notification subscriptions, notification processor. Verified with test events but NO bulk ingestion yet.

## Critical context: what already works (don't rebuild)

The existing `core/amazon_intel/` module is more mature than the brief assumes. **Do not delete it.** Preserve and extend:

| Component | File | Status |
|-----------|------|--------|
| LWA OAuth2 client | `core/amazon_intel/spapi/client.py` | Working for EU/NA/FE |
| Rate limiter | `core/amazon_intel/spapi/client.py` | Basic (429 detection) |
| Sync scheduler | `core/amazon_intel/spapi/scheduler.py` | Working, EU-only (`ACTIVE_REGIONS = ['EU']`) |
| Inventory sync (Reports API) | `core/amazon_intel/spapi/inventory.py` | Working — pulls `GET_MERCHANT_LISTINGS_ALL_DATA` |
| Orders sync | `core/amazon_intel/spapi/orders.py` | Working — 3,025 rows in `ami_orders` |
| Daily traffic sync | `core/amazon_intel/spapi/analytics.py` | Working — 3,897 rows in `ami_daily_traffic` |
| Listings read/write | `core/amazon_intel/spapi/listings.py` | Working — GET/PATCH per SKU |
| Advertising sync | `core/amazon_intel/spapi/advertising.py` | Code complete, profile IDs not discovered (v2 endpoint is 301ing — needs migration to v3) |
| DB schema + helpers | `core/amazon_intel/db.py` | 12 `ami_*` tables |
| API routes | `api/routes/amazon_intel.py` | Full CRUD + sync triggers |
| Cairn context endpoint | `/ami/cairn/context` | Working — feeds chat agent |
| `query_amazon_intel` tool | `core/tools/amazon_intel_tools.py` | Registered in `core/agent.py` — **preserve this** |

## SP-API auth status (verified live 2026-04-13)

| Region | Refresh Token | Auth Test | Seller ID |
|--------|:---:|:---:|---|
| EU | 332 chars | AUTH OK | `ANO0V0M1RQZY9` |
| NA | 332 chars | AUTH OK | `AU398HK55HDI4` |
| FE/AU | 353 chars | AUTH OK | `A35C7AI7WDWERB` |

All three regions authenticate. Tokens are in `/opt/nbne/cairn/deploy/.env` on Hetzner. Seller IDs have hardcoded fallbacks in `client.py`.

## AWS status

- **Account:** NBNE (9150-7785-2106), us-east-1
- **AWS Console access:** Toby has it (IAM, S3, IoT Core recently visited)
- **Current AWS usage in Cairn:** Zero. No boto3, no SQS, no IAM credentials in the codebase.
- **What Session 1 needs to set up:** IAM user with SQS permissions, three SQS queues (eu-west-2, us-east-1, ap-southeast-2), IAM role for Amazon's notification service. Document every step in `docs/cairn/amazon_notifications_setup.md`.

## Ads profile discovery blocker (minor)

The existing `advertising.py` hits `/v2/profiles` which returns 301. Amazon deprecated v2. Fix: migrate to v3 Advertising API (`/v3/profiles`). This is not blocking for the listings pipeline but should be fixed in this session since we're touching the advertising module.

## Toby's modifications to the original brief

### Phase 4.5 added (consumer inventory)

Before Phase 5 (nuke) can run in Session 2, produce a `docs/cairn/amazon_consumers.md` that maps every reference to the old module:

```
grep -rn 'ami_listing_snapshots\|ami_business_report_legacy\|ami_flatfile_data\|build_snapshots\|smart.merge\|amazon_snapshots' \
  --include='*.py' --include='*.ts' --include='*.tsx' --include='*.sql' --include='*.md' \
  D:\claw/
```

For each hit, document: file, line, what it does, and what replaces it. Phase 5 is gated on every entry being checked off.

### Session split confirmed

- **Session 1 (this session):** Phases 0–2 — auth enable, backfill plumbing (new tables + Catalog API enrichment + embedding), notification infrastructure with test events. No bulk data ingestion.
- **Session 2 (separate):** Phases 3–5 — diff pipeline, full backfill execution, consumer migration (4.5), nuke old data.

### query_amazon_intel preservation

The `query_amazon_intel` chat tool (`core/tools/amazon_intel_tools.py`, registered in `core/agent.py`) must survive the migration. In Session 2, it gets pointed at the new schema. In this session, don't touch it — it works against `ami_*` tables that remain intact.

## Database state (row counts as of 2026-04-13)

| Table | Rows | Notes |
|-------|------|-------|
| `ami_sku_mapping` | 5,798 | SKU→ASIN→M-number |
| `ami_flatfile_data` | 9,441 | Parsed Amazon flatfiles |
| `ami_orders` | 3,025 | Order-level, PII-excluded |
| `ami_daily_traffic` | 3,897 | Day-granularity traffic |
| `ami_listing_snapshots` | 28,392 | **Broken** — inflated by smart-merge |
| `ami_business_report_legacy` | 12,862 | **Deprecated** — double-counting |
| `ami_advertising_data` | 6,387 | From Ads API |
| `ami_velocity` | 2,528 | Computed velocity alerts |
| `ami_spapi_sync_log` | 102 | Sync history |
| `ami_uploads` | 81 | Manual CSV upload log |
| `ami_new_products` | 1,029 | Toby's new products list |
| `ami_weekly_reports` | 2 | Generated reports |

## Hetzner deployment

- **Cairn API:** `deploy-cairn-api-1` at `178.104.1.152`, port 8765
- **Cairn DB:** `deploy-cairn-db-1`, PostgreSQL 16 with pgvector
- **Deploy env:** `/opt/nbne/cairn/deploy/.env`
- **Hot-patch pattern:** `docker cp` file into container + `docker compose restart cairn-api`
- **Full rebuild:** `cd /opt/nbne/cairn/deploy && bash build-cairn-api.sh full`

## Success criteria for this session

1. `ACTIVE_REGIONS = ['EU', 'NA', 'FE']` in scheduler, all three syncing on Hetzner
2. New `ami_listing_content` table with schema for full listing content (title, bullets, description, images, A+ refs, variations)
3. Per-ASIN Catalog Items API enrichment code that runs after inventory sync, populating `ami_listing_content`
4. Listing text embeddings in pgvector (title, bullets, description, combined)
5. SQS queues created, IAM configured, notification subscriptions registered
6. Notification processor skeleton that long-polls SQS and logs received events
7. Test event verified per account
8. `docs/cairn/amazon_notifications_setup.md` documenting the AWS setup
9. `docs/cairn/amazon_consumers.md` with the consumer inventory (prep for Session 2)
10. All existing `query_amazon_intel` tool functionality preserved
11. Unit tests for: Catalog API parsing, listing content diffing, embedding generation

## What NOT to do in this session

- Do NOT run a bulk backfill against all ~4,000 ASINs. The plumbing runs, but the full ingestion is Session 2.
- Do NOT delete any existing `ami_*` tables or data.
- Do NOT modify `query_amazon_intel` tool or its schema dependencies.
- Do NOT nuke `ami_listing_snapshots` — that's Session 2 Phase 5.
- Do NOT attempt listing write operations (price/title/bullet updates) — read-only this session.
