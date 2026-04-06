# Amazon Intelligence

## What It Does
Read-only Amazon listing health pipeline. Ingests CSV and XLSM exports from Seller
Central, cross-references with Manufacture margin data via M-numbers, and produces
prioritised weekly underperformance reports with diagnosis codes and recommended
actions. No automated changes to listings — Phase 1 is report-driven.

## Who Uses It
- **Toby Fletcher** — listing health review, improvement prioritisation

## Tech Stack
- Backend: Python (embedded in Cairn FastAPI at core/amazon_intel/)
- Database: 7 ami_* tables in Cairn's PostgreSQL on nbne1
- API routes: /ami/* (mounted in api/routes/amazon_intel.py)
- Memory: SQLite at data/amazon-intelligence.db

## Connections
- **Feeds data to:** [[modules/cairn]] (context endpoint), [[modules/render]] (improvement queue)
- **Receives data from:** [[modules/manufacture]] (M-number + margin data)
- **Context endpoint:** `GET /ami/cairn/context` — SKU health, sales, conversions, ad spend

## Current Status
- Build phase: Phase 1 complete (read-only, report-driven)
- Last significant change: Code embedded in Cairn repo (2026-04-03)
- Known issues: Flatfile column positions vary between category templates
- Data coverage: 4,883 SKU mappings, 2,553 unique M-numbers, 913 unique ASINs

## Key Concepts
- **SKU → M-number mapping:** One M-number maps to multiple marketplace SKUs and ASINs
- **Health scoring (0-10):** Deductions for low conversion, low sessions, lost Buy Box, high ACOS, missing content
- **Diagnosis codes:** CONTENT_WEAK, KEYWORD_POOR, VISIBILITY_LOW, MARGIN_CRITICAL, QUICK_WIN_IMAGES, QUICK_WIN_BULLETS, BUYBOX_LOST, ZERO_SESSIONS
- **Marketplace ASINs:** UK (328), US (310), CA (248), AU (231), DE (19)
- **Data sources:** Inventory Flatfiles (.xlsm), Business Reports (.csv), Advertising Reports (.xlsx)
- **All Listings Report:** Primary SKU→ASIN bridge, boosted join rate from 3.5% to 15%

## Related
- [[modules/manufacture]] — M-number and margin data source
- [[modules/render]] — receives improvement queue for content-weak listings
- [[modules/etsy-intelligence]] — sister module for Etsy marketplace
