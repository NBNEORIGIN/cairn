# Ledger

## What It Does
Financial management system for NBNE. Tracks cash position, revenue by channel,
expenditure, and margins. Provides real-time financial data to the business brain
dashboard so Toby can make informed decisions about production, pricing, and
investment.

## Who Uses It
- **Toby Fletcher** — financial oversight, margin analysis, cash management

## Tech Stack
- Backend: FastAPI + PostgreSQL (DB: ledger, port 5432)
- Frontend: Next.js
- Hosting: Local (D:\ledger, ports 8001/3001)
- Phase 1 complete

## Connections
- **Feeds data to:** [[modules/cairn]] (context endpoint — cash, margins, revenue),
  [[modules/crm]] (margin data for pipeline prioritisation)
- **Receives data from:** [[modules/phloe]] (booking revenue)
- **Context endpoint:** `GET /api/cairn/context` — cash position, revenue MTD/YTD, expenditure

## Current Status
- Build phase: Phase 1 complete
- Last significant change: Initial build (2026)
- Known issues: None documented

## Key Concepts
- **Cash position:** Current bank balance and available funds
- **Revenue MTD/YTD:** Month-to-date and year-to-date revenue tracking
- **Channel margins:** Profit margins broken down by sales channel (Amazon, Etsy, direct)
- **Context endpoint:** Feeds live financial data into the Cairn business brain dashboard

## Related
- [[modules/cairn]] — financial data appears in business brain responses
- [[modules/phloe]] — booking revenue flows in from tenants
- [[modules/crm]] — margin data helps prioritise the sales pipeline
