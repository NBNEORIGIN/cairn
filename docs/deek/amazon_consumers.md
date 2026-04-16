# Amazon Listing Intelligence — Consumer Inventory

**Purpose:** Map every reference to legacy/deprecated tables and functions that will be
replaced or removed in Session 2 Phase 5 (nuke). Phase 5 is gated on every entry here
being checked off with a replacement.

**Date:** 2026-04-13

## Legend

- `ami_listing_snapshots` — Broken. Inflated by smart-merge (28,392 rows vs ~4,000 real ASINs). Being replaced by `ami_listing_content` for content fields and rebuilt snapshot logic.
- `ami_business_report_legacy` — Deprecated. 30-day rolling aggregates that cause double-counting. Replaced by `ami_daily_traffic` + `ami_orders`.
- `ami_flatfile_data` — Still valid for manual uploads but content now comes from Catalog Items API → `ami_listing_content`. Will become secondary/legacy source.
- `build_snapshots()` — Needs rewrite to pull content from `ami_listing_content` instead of `ami_flatfile_data`, and performance from `ami_daily_traffic` instead of `ami_business_report_legacy`.

---

## References by File

### core/amazon_intel/snapshots.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 13 | `build_snapshots()` | Main snapshot assembly function | Rewrite to use `ami_listing_content` for content, `ami_daily_traffic` for performance |
| 21 | `ami_listing_snapshots` | Comment — upsert target | Point to rebuilt `ami_listing_snapshots` or new table |
| 168 | `ami_flatfile_data` | Reads latest flatfile content for snapshot assembly | Read from `ami_listing_content` instead |
| 183 | `ami_business_report_legacy` | Comment — legacy data source | Remove reference, use `ami_daily_traffic` |
| 262 | `ami_listing_snapshots` | `_store_snapshots()` upserts into this table | Keep table but rebuild with clean data |
| 290 | `ami_listing_snapshots` | INSERT SQL | Same — keep table, rebuild logic |
| 340 | `ami_listing_snapshots` | GROUP BY for latest snapshot per ASIN | No change needed |
| 376 | `ami_listing_snapshots` | SELECT for `query_snapshots()` | No change needed |
| 393 | `ami_listing_snapshots` | COUNT for stats | No change needed |
| 405 | `ami_listing_snapshots` | SELECT for `get_latest_snapshot()` | No change needed |

### core/amazon_intel/reports.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 78 | `ami_listing_snapshots` | Weekly report: avg score, counts | Keep — reads from snapshots which will be rebuilt clean |
| 116 | `ami_listing_snapshots` | Underperformers query | Keep |
| 142 | `ami_listing_snapshots` | Quick wins query | Keep |
| 155 | `ami_listing_snapshots` | Margin alerts query | Keep |
| 180 | `ami_listing_snapshots` | Content audit query | Keep |
| 204 | `ami_listing_snapshots` | Full report generation | Keep |
| 312 | `ami_listing_snapshots` | Max snapshot_date | Keep |
| 323 | `ami_listing_snapshots` | Revenue context query | Keep |
| 356 | `ami_listing_snapshots` | Comment about revenue replacement | Keep (documentation) |

### core/amazon_intel/memory.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 123 | `ami_listing_snapshots` | Memory indexing — pushes snapshots to Deek | Keep — will read clean snapshots |
| 158 | `ami_listing_snapshots` | Underperformers for memory context | Keep |

### core/amazon_intel/db.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 72 | `ami_flatfile_data` | CREATE TABLE | Keep table, but stop using for content source |
| 118 | `ami_business_report_legacy` | CREATE TABLE | Keep schema for historical data, stop writes |
| 162 | `ami_listing_snapshots` | CREATE TABLE | Keep and rebuild with clean data from `ami_listing_content` |
| 267 | `ami_business_report_legacy` | Comment — never SUM from legacy | Keep (documentation) |
| 524 | `ami_flatfile_data` | Migration: add listing_created_at | Already applied, keep |
| 525 | `ami_listing_snapshots` | Migration: add listing_created_at | Already applied, keep |

### core/amazon_intel/spapi/scheduler.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 224 | `build_snapshots` | Import and call post-sync | Rewrite `build_snapshots()` internals |
| 225 | `build_snapshots` | Execute snapshot build | Same |

### core/amazon_intel/spapi/analytics.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 11 | `ami_business_report_legacy` | Comment — legacy context | Keep (documentation) |
| 130 | `ami_business_report_legacy` | Comment — retired | Keep (documentation) |
| 133 | `ami_business_report_legacy` | Comment — still read by build_snapshots | Remove after Session 2 |
| 139 | `ami_business_report_legacy` | Commented-out INSERT SQL | Remove dead code |

### core/amazon_intel/spapi/inventory.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 22 | `ami_flatfile_data` | Comment — output target | Keep — inventory sync still writes here, Catalog API enrichment is additive |

### core/amazon_intel/parsers/flatfile.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 310 | `ami_flatfile_data` | Parse + store flatfile rows | Keep for manual uploads, but `ami_listing_content` is primary |
| 327 | `ami_flatfile_data` | INSERT SQL | Keep |

### core/amazon_intel/parsers/business_report.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 190 | `ami_business_report_legacy` | Comment — no longer writes | Keep (documentation) |
| 193 | `ami_business_report_legacy` | INSERT SQL (manual uploads) | Remove — manual uploads should stop |

### core/amazon_intel/parsers/all_listings.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 111 | `ami_flatfile_data` | Comment — also updates flatfile data | Keep |
| 156 | `ami_flatfile_data` | UPDATE ASIN in flatfile data | Keep |
| 167 | `ami_flatfile_data` | UPDATE listing_created_at | Keep |

### core/tools/ami_tools.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 22 | `ami_flatfile_data` | Schema docs for chat tool | Add `ami_listing_content` to docs in Session 2 |
| 41 | `ami_listing_snapshots` | Schema docs for chat tool | Keep, update row count |
| 64 | `ami_flatfile_data` | Notes about data | Update in Session 2 |
| 76-78 | `ami_flatfile_data`, `ami_listing_snapshots` | ALLOWED_TABLES list | Add `ami_listing_content`, `ami_listing_embeddings` in Session 2 |

### core/tools/registry.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 303-305 | `ami_flatfile_data`, `ami_listing_snapshots` | Tool description string | Update in Session 2 |

### core/wiki/compiler.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 293 | `ami_listing_snapshots` | Wiki compiler reads snapshots for module articles | Keep — will read clean snapshots |

### api/routes/amazon_intel.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 23 | `ami_listing_snapshots` | Health check — counts snapshots | Keep |
| 141-143 | `build_snapshots` | Route to trigger snapshot build | Keep route, rewrite internals |

### api/routes/analytics.py

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 8 | `ami_business_report_legacy` | Comment — never query for revenue | Keep (documentation) |
| 36-37 | `ami_listing_snapshots` | Comment — don't use for revenue | Keep (documentation) |
| 343 | `ami_business_report_legacy` | MAX(created_at) for freshness check | Switch to `ami_daily_traffic` in Session 2 |

### projects/amazon-intelligence/core.md

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 68-70 | `ami_flatfile_data`, `ami_business_report`, `ami_listing_snapshots` | Architecture diagram | Update in Session 2 |
| 85 | `build_snapshots()` | Sync chain diagram | Update in Session 2 |
| 99-102 | `ami_flatfile_data`, `ami_listing_snapshots` | Table list | Add `ami_listing_content` |

### wiki/modules/amazon-analytics.md

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 19-20 | `ami_business_report_legacy`, `build_snapshots()` | Wiki docs | Update in Session 2 |
| 60 | `build_snapshots()` | Sprint 2 scope note | Execute in Session 2 |
| 77 | `ami_business_report_legacy`, `build_snapshots()` | Legacy dependency note | Remove after Session 2 |

### wiki/modules/amazon-intelligence.md

| Line | Reference | What It Does | Replacement |
|------|-----------|-------------|-------------|
| 37 | `ami_flatfile_data` | Architecture diagram | Add `ami_listing_content` path |
| 40 | `ami_listing_snapshots` | Architecture diagram | Keep, note rebuild |

---

## Session 2 Action Plan

### Phase 3 (Diff Pipeline)
1. `build_snapshots()` → rewrite to read content from `ami_listing_content` instead of `ami_flatfile_data`
2. `build_snapshots()` → rewrite to read performance from `ami_daily_traffic` instead of `ami_business_report_legacy`

### Phase 4 (Full Backfill)
1. Run `enrich_asins()` across all ~4,000 ASINs in all three regions
2. Run `embed_all_listings()` for all marketplaces

### Phase 4.5 (Consumer Migration)
1. Update `core/tools/ami_tools.py` — add `ami_listing_content` and `ami_listing_embeddings` to ALLOWED_TABLES and schema docs
2. Update `core/tools/registry.py` — update tool description
3. Update `projects/amazon-intelligence/core.md` — architecture diagram
4. Update `wiki/modules/amazon-intelligence.md` — architecture docs
5. Remove dead code in `core/amazon_intel/spapi/analytics.py` (commented-out INSERT)

### Phase 5 (Nuke)
1. TRUNCATE `ami_listing_snapshots` — rebuild with clean data
2. DROP ami_business_report_legacy` — verify nothing reads it anymore
3. Mark `ami_flatfile_data` as secondary source (manual uploads only)
4. Delete commented-out business_report INSERT in `parsers/business_report.py`
5. Run clean `build_snapshots()` to repopulate snapshots from `ami_listing_content`

**Gate:** Every row in the tables above must have a ✓ in the Replacement column before Phase 5 runs.
