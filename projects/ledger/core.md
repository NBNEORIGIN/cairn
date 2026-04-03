# Ledger — Domain Context
# NBNE Financial Management System

## Purpose
Operational financial intelligence. Not accounting. Answers: what did we earn,
what did we spend, what is our cash position, what do we need to reorder?

## Stack
- Backend: FastAPI (port 8001)
- Frontend: Next.js + shadcn/ui + Tailwind (port 3001)
- Database: PostgreSQL (port 5433)
- AI: Claude Sonnet for procurement chat

## Revenue Channels
- Amazon UK, US, CA, FR, DE, AU (CSV/TSV upload — SP-API deferred to Phase 2)
- Etsy (CSV upload)
- eBay (CSV upload)
- Phloe bookings (API pull from Phloe /api/cairn/context)
- B2B commercial invoices (manual entry)

## Cost Categories
- Cost of goods (material costs per product — links to Manufacture M-numbers)
- Postage (per order, per channel)
- Amazon fees (FBA, referral — extracted from Amazon reports)
- Fixed costs (rent, utilities, subscriptions — monthly manual entry)
- Procurement (supplier invoices — Dext integration Phase 2)
- Advertising (Google Ads, Amazon PPC — manual entry Phase 1, API Phase 2)

## Key Metrics
- Gross revenue by channel (daily, weekly, monthly, YTD)
- Gross margin by channel and by product (M-number)
- Cash position and trajectory
- Postage cost per order average
- Procurement alerts (items below reorder threshold)

## Integration Points
- Manufacture: M-number cost data (material + machine time)
- Phloe: booking revenue via /api/cairn/context
- Cairn: exposes /api/cairn/context for business brain
- Dext: receipt/invoice scanning (Phase 2)
- Amazon SP-API: automated report pull (Phase 2)

## Phase 1 Data Ingestion (manual CSV upload)
All channel data enters via CSV/TSV upload in Phase 1.
No live API connections in Phase 1 except Phloe.
SP-API, Dext, and Google Ads API connections are Phase 2.

## Users
- Toby: all access, financial analysis
- Jo: invoice entry, cash position view, expenditure entry
- Gabby/Ivan/Ben/Sanna: read-only dashboard (if needed)

## Hard Rules
- Never store money as floats — always NUMERIC/Decimal
- Never auto-delete imported data
- Cairn context endpoint must always return valid JSON even if data is empty
- All CSV imports are idempotent (dedup by channel + order_id)
- One logical change per commit
