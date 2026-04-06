# Manufacture

## What It Does
Production management system for NBNE's Origin Designed product range. Tracks
product definitions (M-numbers), production pipeline stages, FBA shipments, stock
levels across multiple sales channels, and machine assignments. Currently being
built to replace the master Excel workbook.

## Who Uses It
- **Toby Fletcher** — product design, production planning, stock management
- **Production staff** — daily make-list, machine assignments, shipment packing

## Tech Stack
- Backend: Django + PostgreSQL (planned)
- Frontend: Next.js (planned)
- Hosting: Hetzner (manufacture.nbnesigns.co.uk, ports 8015/3015)
- Current authority: Excel workbook (Shipment_Stock_Sheet.xlsx)

## Connections
- **Feeds data to:** [[modules/amazon-intelligence]] (M-number + margin data),
  [[modules/cairn]] (context endpoint)
- **Receives data from:** [[modules/render]] (ASIN mapping)
- **Context endpoint:** `GET /api/cairn/context` — make list, machine status, stock alerts

## Current Status
- Build phase: All phases deployed to manufacture.nbnesigns.co.uk
- Last significant change: Full deployment (March 2026)
- Known issues: Excel workbook remains authoritative reference during transition

## Key Concepts
- **M-number:** Master product reference (M0001, M0002, etc.) — permanent, never modified once assigned
- **Blank:** Physical substrate a product is printed on, named after infamous people:
  DONALD (circular), SAVILLE (aluminium), DICK (acrylic), STALIN (large format),
  MYRA, IDI, TOM (memorial stake), JOSEPH, HARRY, AILEEN
- **Machine names:** ROLF (UV flatbed), MIMAKI (sublimation), MUTOH (wide-format),
  ROLAND (vinyl cutter), EPSON (sublimation), HULKY (large-format)
- **Production pipeline:** Designed → Printed → Processed → Cut → Labelled → Packed → Shipped
- **Sales channels:** UK, US, CA, AU, EBAY, ETSY, FR
- **FBA:** Fulfilled By Amazon — stock held in Amazon warehouse DIP1

## Related
- [[modules/amazon-intelligence]] — listing health uses M-number data
- [[modules/etsy-intelligence]] — Etsy listings map to M-numbers
- [[modules/render]] — publishes product designs to marketplaces
