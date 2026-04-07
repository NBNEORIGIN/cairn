# Render

## What It Does
AI-driven product design and publishing system for NBNE's Origin Designed range.
Takes a product concept through to live listings on Amazon, Etsy, eBay, and the
NBNE website (app.nbnesigns.co.uk/shop). Staff refer to it internally as "new
products." This is the most critical piece of software NBNE has developed.

## Who Uses It
- **Gabby** — daily product creation, QA approval, Amazon flatfile generation
- **Toby Fletcher** — product design, listing strategy, publishing decisions

## Tech Stack
- Backend: Flask 3.0 / Python, Gunicorn (1 worker)
- Database: render_* tables in Cairn PostgreSQL on nbne1 (192.168.1.228:5432/claw)
- Image generation: Playwright (headless Chromium), Pillow
- AI content: Claude Sonnet (listings), DALL-E 3 (lifestyle images), GPT-4o (chat)
- Hosting: Hetzner 178.104.1.152 (migrating to nbne1)
- GitHub: NBNEORIGIN/render
- Local path: D:\render

## Database Tables (render_ prefix)
| Table | Purpose |
|-------|---------|
| render_products | M-number catalogue, QA status, AI content |
| render_blanks | Physical sign substrate dimensions (5 sizes) |
| render_product_content | AI-generated titles, descriptions, bullets, search terms |
| render_product_images | Generated image URLs per product |
| render_users | Staff authentication (5 users) |
| render_sales_imports | Amazon sales report audit trail |
| render_sales_data | Aggregated sales metrics |
| render_batches | Background job tracking |
| render_publish_log | Cross-channel publish history (etsy, amazon, ebay, phloe) |

## Connections
- **Publishes to:** Etsy (direct API, draft listings), eBay (Inventory API + Marketing), Amazon (XLSX flatfile), Phloe shop (auto on QA approve)
- **Feeds data to:** [[modules/manufacture]] (ASIN mapping), [[modules/amazon-intelligence]] (published listings)
- **Receives data from:** [[modules/amazon-intelligence]] (improvement queue for content-weak listings)
- **Context endpoint:** `GET /api/cairn/context` — product pipeline state, publish counts, recent activity

## Publishing Channels

### Etsy (Direct API)
- OAuth 2.0 PKCE flow at /etsy/oauth/connect
- Creates draft listings (staff review before activating)
- Shop ID: 11706740, Taxonomy: 2844 (Signs)
- Rate limited: 5 QPS
- Route: `POST /api/etsy/publish`

### eBay (Direct API)
- Inventory API + Marketing API (auto-promote at 5% CPS)
- Category: 166675 (Signs & Plaques)

### Amazon (XLSX flatfile)
- Generated via `POST /api/export/amazon-flatfile-download`
- Manual upload to Seller Central

### NBNE Website (Phloe auto-publish)
- Auto-triggers when product QA status changes to 'approved'
- Pushes to app.nbnesigns.co.uk/shop via Django API
- JWT auth, tenant: mind-department
- Route: `POST /api/phloe/publish`

## Current Status
- Build phase: Production (Hetzner), migration to nbne1 in progress
- Last significant change: DB migration to Cairn PG, Etsy direct publish, Phloe auto-publish (2026-04-07)
- Known issues: Hetzner→nbne1 migration incomplete (deploy scripts ready, data migration pending)

## Key Concepts
- **Product publishing pipeline:** Concept → SVG render → AI content → QA approve → auto-publish to all channels
- **5 blanks:** dracula (9.5cm), saville (11cm), dick (14cm), barzan (19cm), baby_jesus (29cm)
- **3 finishes:** silver, gold, white
- **QA gate:** Non-negotiable — no product publishes without QA approval
- **Draft-only Etsy:** All Etsy listings created as draft, never directly active
- **Studio (planned):** Local FLUX lifestyle images when second RTX 3090 arrives

## Related
- [[modules/manufacture]] — M-number and blank data for product definitions
- [[modules/amazon-intelligence]] — listing health drives improvement queue
- [[modules/etsy-intelligence]] — Etsy listings health scoring (read-only analytics)
- [[modules/ledger]] — revenue tracking from all marketplace channels
