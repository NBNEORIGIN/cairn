# Etsy Intelligence

## What It Does
Etsy listing health and sales intelligence for NBNE. Mirrors the Amazon Intelligence
pattern but uses the Etsy API v3 instead of CSV uploads. Ingests shop and listing
data, health-scores listings with 13 Etsy-specific checks, and exposes a context
endpoint for the business brain dashboard.

## Who Uses It
- **Toby Fletcher** — Etsy listing review, sales tracking

## Tech Stack
- Backend: Python (embedded in Cairn FastAPI at core/etsy_intel/)
- Database: 4 etsy_* tables in Cairn's PostgreSQL on nbne1
- API routes: /etsy/* (mounted in api/routes/etsy_intel.py)
- Etsy API: v3, 5 QPS rate limiting via asyncio semaphore

## Connections
- **Feeds data to:** [[modules/cairn]] (context endpoint)
- **Receives data from:** [[modules/manufacture]] (M-number mapping, planned)
- **Context endpoint:** `GET /etsy/cairn/context` — listing health, sales data

## Current Status
- Build phase: Phase 1 complete (API-driven ingestion)
- Last significant change: Phase 1 implementation (2026-04-04)
- Known issues: Receipt/sales endpoint requires OAuth token — currently degrades gracefully with API key only

## Key Concepts
- **Etsy shops:** NBNE Print and Sign (main store), Copper Bracelets Shop (secondary)
- **Health scoring (0-10):** 13 Etsy-specific checks mirroring AMI pattern
- **API-driven:** Unlike AMI's CSV uploads, Etsy Intelligence pulls data directly from the Etsy API
- **Graceful degradation:** Sales data requires OAuth; listings work with API key only

## Related
- [[modules/amazon-intelligence]] — sister module for Amazon marketplace
- [[modules/manufacture]] — M-number product data (planned integration)
- [[modules/cairn]] — context endpoint feeds business brain
