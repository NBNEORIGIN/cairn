# Phloe

## What It Does
Multi-tenant booking platform for UK micro and small businesses. Each tenant gets
their own branded booking page where clients can book appointments, classes, tables,
or food orders. Phloe handles the booking logic, reminders, payments via Stripe, and
client communications. Positioned as Workflow-as-a-Service (WaaS).

## Who Uses It
- **Toby Fletcher** — development, infrastructure, strategy
- **Joanne Tompkins** — co-director, tenant onboarding and support
- **DemNurse** (Amy Law) — nursing/healthcare bookings
- **Ganbaru Kai** (Chrissie Howard) — martial arts, events, gradings
- **Amble Pin Cushion** (Norma) — haberdashery, workshops, shop
- **NAPCO Pizza** (Allison Joynson) — food ordering
- **Real Fitness** (Ami) — prospect, not yet onboarded

## Tech Stack
- Backend: Django 5.x + PostgreSQL (per-tenant isolated databases)
- Frontend: Next.js (TypeScript)
- Hosting: Hetzner Nuremberg (178.104.1.152)
- Email: Postmark
- Payments: Stripe (per-tenant accounts)
- Domain: phloe.co.uk

## Connections
- **Feeds data to:** [[modules/ledger]] (booking revenue), [[modules/cairn]] (context endpoint)
- **Receives data from:** None (standalone SaaS)
- **Context endpoint:** `GET /api/cairn/context` — tenant count, booking volume, active paradigms

## Current Status
- Build phase: Production (4 booking paradigms live)
- Last significant change: Events module shipped (2026-03-30), Postmark email migration (April 2026)
- Known issues: Locale-awareness needed for international expansion
- Disaster recovery: Ark project provides pg_dump + Docker volume backups
- Pricing: £200 one-off setup + £40/month (beta programme closed)

## Key Concepts
- **Booking paradigms:** appointment, class/timetable, table reservation, food ordering — all are the same underlying state machine with different configuration surfaces
- **One booking paradigm:** strategic insight (2026-03-29) — all booking types share the same engine; differences are workflow attachments and presentation
- **Tenants:** independent businesses using Phloe, each with isolated database
- **WaaS:** Workflow-as-a-Service — Phloe's market positioning
- **Events:** bookings with capacity, pricing, and dates (shipped 2026-03-30)

## Related
- [[modules/ledger]] — booking revenue feeds financial reporting
- [[modules/cairn]] — memory and context integration
