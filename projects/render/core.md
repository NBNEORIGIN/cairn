# Render — Deek Agent Core Context
# Version: 2.0
# Updated: 2026-04-06

## What this is

Render (formerly SignMaker) is NBNE's AI-driven, semi-automated small-format signage
product design and publishing system. It takes a product concept through to live
listings on Amazon, Etsy, eBay, and the NBNE website (app.nbnesigns.co.uk/shop).

It is the most important piece of software NBNE has developed. All architectural
decisions here are written back at Opus level.

## Repository

- GitHub: https://github.com/NBNEORIGIN/render
- Local: D:\render
- Stack: Flask 3.0 + Gunicorn, PostgreSQL (Deek deek DB on nbne1), Playwright, Pillow
- Database: render_ prefixed tables in postgresql://cairn:cairn_nbne_2026@192.168.1.228:5432/claw
- Deploy: Docker on nbne1 (192.168.1.228), public via Cloudflare Tunnel at render.nbnesigns.co.uk

## What it does

1. Product management — M-number catalogue with sizes, colours, layout modes, pricing
2. Image generation — 4 image types per product from SVG templates via headless Chromium
3. AI content — Claude Sonnet generates SEO-optimised Amazon/Etsy/eBay copy
4. QA approval queue — side-by-side image review per product
5. Etsy direct publish — OAuth 2.0 PKCE flow, creates draft listings + uploads images via API
6. eBay direct publish — OAuth, Inventory API + Marketing API auto-promote
7. Amazon export — XLSX flatfiles for Seller Central upload
8. Website publish — auto-push QA-approved products to app.nbnesigns.co.uk/shop via Phloe API
9. Deek context — /api/cairn/context exposes pipeline state to business brain
10. AI product assistant — GPT-4o chat for product development guidance

## Database tables (render_ prefix in deek DB)

- render_products — M-number catalogue, QA status, AI content
- render_blanks — physical sign substrate dimensions
- render_product_content — AI-generated titles, descriptions, bullets, search terms
- render_product_images — generated image URLs per product
- render_users — staff authentication
- render_sales_imports — Amazon sales report audit trail
- render_sales_data — aggregated sales metrics
- render_batches — background job tracking
- render_publish_log — publish history across all channels (etsy, amazon, ebay, phloe)

## Product dimensions

- 5 sizes: dracula / saville / dick / barzan / baby_jesus (9.5cm → 29cm)
- 3 finishes: silver / gold / white
- 2 mounting types
- 6 layout modes (A–F) controlling icon/text placement
- 106 SVG templates covering all combinations

## Non-negotiable rules

1. Never publish a product that isn't QA-approved. The approval gate prevents broken listings.
2. All Etsy listings created as **draft** — staff review before activating.
3. Read sizes/prices from config.py only. Never duplicate SIZE_CONFIG elsewhere.
4. Never access Render's database directly from Deek — use /api/cairn/context endpoint.
5. Authentication required on all routes except /health, /login, /etsy/oauth/callback.
6. Keep export_etsy.py as fallback — don't delete it even though direct API publish exists.

## Etsy integration

- API key: ETSY_API_KEY + ETSY_SHARED_SECRET (colon-separated in x-api-key header)
- Shop ID: 11706740 (NorthByNorthEastSign)
- Taxonomy: 2844 (Signs), Shipping profile: 208230423243, Return policy: 1074420280634
- OAuth: PKCE flow at /etsy/oauth/connect → callback. Tokens in etsy_tokens.json (gitignored)
- Publish: POST /api/etsy/publish with m_numbers or all_approved
- Rate limit: 5 QPS enforced in etsy_api.py

## Studio integration (planned)

Studio (ComfyUI / FLUX) will feed into the Render lifestyle image pipeline.
Current DALL-E 3 lifestyle generation is the placeholder. When the second RTX 3090
arrives, the image source should become pluggable: DALL-E 3 (API fallback) vs
local FLUX (primary).

## Decision Log

### 2026-03-30 — Project renamed SignMaker → Render, registered in Deek

### 2026-04-06 — DB migrated to Deek PG, Etsy direct publish, Deek integration

**Decision**: Moved from standalone Docker PG to render_ prefixed tables in Deek's
deek database on nbne1. Removed SQLite fallback. Added Etsy OAuth 2.0 PKCE flow
and direct API publishing (etsy_auth.py, etsy_api.py). Added /api/cairn/context
endpoint for business brain. Added render_publish_log table for cross-channel
publish tracking.

**Rejected**: Keeping separate database — prevents Deek from accessing product data
for business intelligence. Keeping Shop Uploader middleware — adds manual step,
slower, no automation possible.
