# Etsy Intelligence — Core Context

## What this is
Etsy listing health and sales intelligence for NBNE. Mirrors the Amazon Intelligence
pattern: ingest data via API, store in PostgreSQL, health score listings, produce
reports, expose a Cairn context endpoint for the business brain dashboard.

## NBNE Etsy presence
- **Etsy NBNE Print and Sign** — main store (signs, memorial plaques, custom products)
- **Etsy Copper Bracelets Shop** — secondary store
- Sales channels also include eBay Origin Designers (future integration)

## API access
- Etsy API v3: https://api.etsy.com/v3
- App: publisher (Personal Access)
- Rate limit: 5 QPS / 5K QPD
- Credentials stored in Cairn memory (reference_etsy_api.md) — load via env vars

## Architecture
Code lives inside the Cairn repo (same pattern as Amazon Intelligence):
- Core logic: `core/etsy_intel/`
- API routes: `api/routes/etsy_intel.py` (mounted at `/etsy/*`)
- Database: `etsy_intelligence` tables in Cairn's PostgreSQL on nbne1
- Connection: postgresql://cairn:cairn_nbne_2026@192.168.1.228:5432/claw

## Decision Log

### 2026-04-04 — Project registered in Cairn
**Context**: Toby provided Etsy API credentials, wants Etsy integration mirroring AMI
**Decision**: Register as Cairn project, code inside Cairn repo following AMI pattern
**Rejected**: Standalone repo (unnecessary — AMI proved embedded pattern works)
