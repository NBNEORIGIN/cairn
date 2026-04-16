# CRM

## What It Does
B2B project management and business development platform for NBNE's commercial
signage work. Tracks client relationships, project pipeline, quotes, emails, and
materials. The primary use case is the "boardroom scenario" — Toby asks Deek a
question while with a client, and Deek searches semantically across all CRM data
to return relevant past projects, materials, methods, and pricing.

## Who Uses It
- **Toby Fletcher** — client meetings, quoting, pipeline management
- **Sales team** — lead tracking, follow-ups

## Tech Stack
- Backend + API: Next.js
- Database: PostgreSQL + pgvector on nbne1 (DB: cairn_crm)
- AI: Migrating from Llama to Deek hybrid search
- Hosting: Hetzner (crm.nbnesigns.co.uk), migrating from Vercel
- Email: cairn@nbnesigns.com (dedicated), sales@nbnesigns.co.uk (read-only), toby@nbnesigns.com (read-only)
- GitHub: NBNEORIGIN/crm

## Connections
- **Feeds data to:** [[modules/cairn]] (semantic search across projects, quotes, emails, materials)
- **Receives data from:** [[modules/ledger]] (margins for pipeline prioritisation),
  [[modules/manufacture]] (capacity for quoting decisions)
- **Context endpoint:** Integrated via Deek's web stream proxy (CRM semantic search)

## Current Status
- Build phase: Live at crm.nbnesigns.co.uk
- Last significant change: Registered as Deek project (2026-04-04)
- Pipeline: £50,309 total (18 leads, 13 quoted, 6 in production)
- Active projects: Bamburgh Golf Club, Paton & Co Estate Agents, Glendale Show
- Backup: Contabo nightly (automatic)

## Key Concepts
- **Boardroom scenario:** Toby queries Deek during a client meeting for instant access to relevant history
- **Semantic search:** BM25 + pgvector retrieval across projects, quotes, emails, materials, knowledge base
- **Pipeline stages:** Lead → Quoted → In Production → Complete
- **Three email sources:** Dedicated cairn@, sales@ (historical), toby@ (direct correspondence)

## Related
- [[modules/cairn]] — semantic search integration
- [[modules/ledger]] — margin data for quote prioritisation
- [[modules/manufacture]] — capacity data for production scheduling
