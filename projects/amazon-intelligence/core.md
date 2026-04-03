# Amazon Listing Intelligence — Core Context

## What this is
A read-only Amazon listing health pipeline for NBNE. Ingests CSV/XLSM exports from Seller Central, cross-references with Manufacture margin data, and produces prioritised weekly underperformance reports with diagnosis codes and recommended actions.

**Phase 1 is read-only and report-driven. No automated changes to listings.**

## Data sources
1. **Inventory Flatfiles** (.xlsm) — listing content: titles, bullets, images, pricing. Downloaded from Seller Central per category template. Column positions vary between templates — parser MUST use Row 4 header name matching, not column indices.
2. **Business Reports** (.csv) — performance: sessions, conversion rate, Buy Box %, units sold. Per-marketplace from Seller Central.
3. **Advertising Reports** (.xlsx/.csv) — ad spend, ACOS, ROAS, keyword performance. From Advertising Console.

## Critical data model: SKU → M-number mapping
One M-number maps to MULTIPLE marketplace SKUs and ASINs. The canonical mapping file is `Shipment_Stock_Sheet_-_ASSEMBLY.csv` (4,883 rows, 3,984 unique SKUs, 2,553 unique M-numbers, 913 unique ASINs).

SKU prefix patterns: OD* (1,034), M-number direct (1,043), OP* (432), OM* (194), OC* (36), OPS*, OPL*, RS*, JS-*, FR-*, VN-*

Marketplace ASINs: UK (328), US (310), CA (248), AU (231), DE (19)

## Blank names (canonical substrate names)
SAVILLE (450), DICK (342), BARZAN (306), DRACULA (296), BABY JESUS (296), STALIN (100), DONALD, etc. Use verbatim in all code.

## Health scoring (0-10)
Deductions for: low conversion (<8%), low sessions (<50), lost Buy Box (<90%), high ACOS (>25%), low margin (<20%), missing bullets (<5), few images (<6), no description, short title.

## Diagnosis codes
CONTENT_WEAK, KEYWORD_POOR, VISIBILITY_LOW, MARGIN_CRITICAL, QUICK_WIN_IMAGES, QUICK_WIN_BULLETS, BUYBOX_LOST, ZERO_SESSIONS, NO_PERFORMANCE_DATA

## Calibration from real data
- Only 1% of listings have all 5 bullet points filled
- 92% have a main image, average 4.2 images per listing
- Parent/child: ~11% parents, ~72% children, ~17% standalone
- Score child ASINs, not parents (parents are containers)

## Related projects
- **manufacturing** — provides margin data via M-number join
- **render** — receives improvement queue for content-weak listings
- **claw** — Cairn memory integration and context endpoint

## Build sections
0. SKU → M-number mapping table + stock sheet seed
1. Upload interface and parsers (flatfile, business report, advertising)
1.5. Cowork-assisted weekly downloads (Phase 1.5, after manual uploads proven)
2. Snapshot assembly and storage
3. Health scoring, diagnosis, weekly report
4. Cairn memory integration + context endpoint
5. Render improvement queue integration
6. Upload and report UI

## Decision Log

### 2026-04-03 — Project registered in Cairn
**Context**: Toby provided a comprehensive implementation brief for Amazon listing intelligence
**Decision**: Registered as standalone Cairn project (amazon-intelligence), not part of Manufacture. Spans three projects (manufacturing, render, claw). Codebase at D:\amazon_intelligence.
**Rationale**: Cross-module scope requires its own project identity. Individual ASIN snapshots stay in listing_snapshots table, not in Cairn memory (would flood search). Weekly summaries go to memory.
**Rejected**: Building inside Manufacture app (wrong scope), using SP-API (hostile to set up, manual downloads are fine for Phase 1)
