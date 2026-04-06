# Render

## What It Does
AI-driven product design and publishing system for NBNE's Origin Designed range.
Takes a product concept through to live listings on Amazon, Etsy, eBay, and the
NBNE website. Staff refer to it internally as "new products." This is the most
critical piece of software NBNE has developed — treat with the same care as Phloe.

## Who Uses It
- **Toby Fletcher** — product design, listing creation, publishing decisions

## Tech Stack
- Backend: Flask / Python
- Hosting: Migrating from Render.com to Hetzner
- GitHub: NBNEORIGIN/render
- Local path: D:\render

## Connections
- **Feeds data to:** [[modules/manufacture]] (ASIN mapping),
  [[modules/amazon-intelligence]] (published listings)
- **Receives data from:** [[modules/amazon-intelligence]] (improvement queue for content-weak listings)
- **Context endpoint:** TBC

## Current Status
- Build phase: Development (migrating hosting)
- Last significant change: Registered as Cairn project
- Known issues: Hosting migration from Render.com to Hetzner in progress

## Key Concepts
- **Product publishing pipeline:** Concept → Design → Listing content → Publish to marketplaces
- **Multi-channel:** Amazon (UK, US, CA, AU), Etsy, eBay, NBNE website
- **Improvement queue:** AMI identifies content-weak listings, Render receives the queue for content refresh
- **Studio (planned):** Downstream lifestyle product image and video generation (requires second RTX 3090)

## Related
- [[modules/manufacture]] — M-number and blank data for product definitions
- [[modules/amazon-intelligence]] — listing health drives improvement queue
- [[modules/etsy-intelligence]] — Etsy listings published through Render
