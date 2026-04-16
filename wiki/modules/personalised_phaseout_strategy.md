# NBNE — Personalised Product Phase-Out Strategy
# For Deek memory and ongoing strategic reference
# Compiled: April 2026

---

## The Problem

Personalised products are structurally unprofitable at scale:

- **Labour scales 1:1** — every order requires a human to read custom
  text, set up a file, and produce a one-off. 2× orders = 2× labour time.
- **Generic products scale ~1:5 or 1:6** — batch manufacturing,
  template-based design, n8n automation. 2× production ≈ 5-6× output.
- At £19.99 retail (main personalised memorial SKU), after Amazon fees
  (~£6.50-7.00) and materials (~£1.50-2.50), roughly £10-11 remains
  to cover personalisation labour — which is where Jo and Gabby's time
  is consumed invisibly.
- The same staff member (Sanna) who makes personalised products also
  publishes generic products. Every hour on personalised is a direct
  opportunity cost against generic catalogue growth.
- Personalised products cannot be FBA'd at volume — they require
  fulfilment after personalisation, preventing Prime badge benefits.

---

## The Strategic Decision

**Phase out all personalised products. Replace with generic products.**

Not because personalised products aren't profitable in isolation,
but because:
1. They prevent scaling
2. They consume disproportionate staff time (and cause stress)
3. Generic products are a better long-term business
4. Amazon dependency reduction requires a broader, automated catalogue

The target is not 0% personalised overnight — it is a managed
transition over 18-24 months that protects revenue while generic
products reach maturity.

---

## The Plan

### Phase 1 — Black & White Memorial Range (IMMEDIATE/DONE)
The most pressing case. Black acrylic stakes with white UV ink printed
on the MUTOH printer.

**The problem:** Machine degraded from 12 units/hour to 2-3 units/hour.
At £15/hour staff rate, unit labour cost increased ~5×. Products
became loss-making at current price points.

**Decision (early April 2026):** Turn these off. Not phase out — off.

**Rationale:**
- Labour cost blow-out makes them unprofitable at any reasonable price
- Sanna finds the broken process stressful and frustrating
- A replacement UV printer arrived but was unproven at decision time
- Metallic/coloured variants on functioning equipment capture
  diverted demand (same emotional purchase, same customer need)
- Sanna's time released to generic product publishing

**Status:** Decision made. Listings to be turned off.

### Phase 2 — Main Personalised Memorial Listing (PRICE LADDER)
Primary product: personalised memorial plaque stake (ASIN B07J3HDB2Y /
B0CVHJBB5Z). 311 reviews, 4.8 stars, Amazon's Choice, £19.99.

**Strategy: price-led phase-out rather than hard switch-off.**

Rationale: Switching off a 4.8-star, 310+ review, Amazon's Choice
listing destroys a valuable asset. A price ladder either:
a) Migrates customers to generic pre-designed equivalents (preferred)
b) Reduces volume to a sustainable premium level
c) Generates higher margin per unit while volume naturally declines

**Price ladder:**
```
Phase 1:  Now → end of May 2026     £19.99 → £22.99
Phase 2:  June → August 2026        £22.99 → £25.99
Phase 3:  September → November 2026 £25.99 → £29.99
Phase 4:  January 2027              Evaluate:
          - If volume sustainable at premium: maintain
          - If volume negligible: wind down listing
```

**Status as of April 2026:** Phase 1 not yet actioned.
Price is still at £19.99. Phase 1 increase to £22.99 is overdue.

**In parallel:** Push pre-designed generic memorial SKUs
(Dad, Mum, Brother, Baby, pets etc.) at or below £19.99 on
Prime FBA. Amazon's algorithm redirects price-sensitive buyers
from the personalised listing to the generics automatically.
Zero-labour products cannibalise labour-intensive ones by design.

### Phase 3 — Broader Personalised Catalogue
All remaining personalised SKUs across all categories.

**Timeline: 18-24 months from December 2025.**

**Mathematical reality:**
- 6-month product maturity period on Amazon means products launched
  today contribute zero revenue for 6 months
- At a 7-8% success rate on generics (70-80 successful from ~1,026
  published since December 2025 — tracking slightly ahead of the
  10% assumption), roughly 12-15 new products per month sustained
  over 18-24 months replaces the personalised revenue base
- This is achievable with Sanna's time fully redirected to publishing

**Recommended launch rate:**
```
Conservative (24-month):  18-20 products/month
Target (18-month):        25-30 products/month
Aggressive (12-month):    40+ products/month (very challenging)
```

Current publish rate since December 2025: ~1,026 products /
~4 months ≈ **256 products/month** — this is ahead of all
scenarios if maintained, but likely includes legacy work.
Verify current sustainable rate with Sanna/Gabby.

---

## The Generic Product Strategy Running in Parallel

### What's working
Pre-designed relationship-specific memorial SKUs (Dad, Mum, Brother,
Sister, Grandad, Grandma, Baby, pets) feel personal to buyers but
require zero personalisation labour. Batch-produced, FBA-shipped,
Prime-eligible. These are the core replacement products.

**Key product categories to expand:**
- Push/pull sign variants (materials, sizes, languages — DONALD blank)
- Safety signs (complete sets, new applications)
- Toilet/bathroom signs (SAVILLE, DICK blanks)
- Memorial pre-designed range (all relationships, all blanks)
- French language variants (growing FR marketplace)
- Large format signs (STALIN blank — underexploited)

### Success metrics being tracked
- Success rate per published product (target: >10%, currently ~7-8%)
- Time to first sale (benchmark: <90 days for traction signal)
- Average successful product monthly revenue (target: £400+/month at maturity)
- Products in maturity pipeline (6-month lag visibility)

### The n8n automation
Publishing automation via n8n reduced time per product significantly.
Template-based design with Sanna handling batch artwork.
Continued investment in automation is the multiplier on this strategy.

---

## Implications for Deek / Manufacturing App

### Data Deek needs to track
1. **M-number status per product** — personalised / pre-designed generic /
   fully generic (no personalisation option)
2. **Price ladder progress** — current price vs target price per SKU,
   next price change date
3. **Phase-out status** — active / price ladder in progress /
   turned off / turned off pending stock clearance
4. **Generic replacement product** — which generic M-number(s)
   replace each personalised SKU being phased out
5. **Labour time per product type** — personalised vs generic,
   to validate the phase-out economics over time

### Manufacturing app decisions influenced by this strategy
- New M-numbers for personalised products: require strong justification
  before assigning (strategic direction is away from personalised)
- Generic variants of existing personalised designs: prioritise these
  in the production queue
- Sanna's capacity: treat as generic publishing capacity, not
  personalised production capacity
- MUTOH/UV printer: when repaired, evaluate whether black memorial
  production restarts or whether that capacity goes to generic UV prints

### Pricing intelligence
The price ladder on the main personalised memorial listing needs
to be tracked and actioned on schedule. Manufacture/Ledger should
flag when the next price change is due.

---

## Key Dates and Actions Outstanding

```
OVERDUE:
[ ] Phase 1 price increase: £19.99 → £22.99 on B07J3HDB2Y
    Was due "now → end of May 2026" — action immediately

PENDING:
[ ] Black & white memorial listings: turn off on Amazon
[ ] Phase 2 price increase: £22.99 → £25.99 (June 2026)
[ ] Phase 3 price increase: £25.99 → £29.99 (September 2026)
[ ] January 2027: evaluate main personalised listing — maintain or wind down
[ ] Track and report generic publish rate monthly vs 25-30/month target

ONGOING:
[ ] Sanna: maintain generic product publishing rate
[ ] Generic memorial range: maintain FBA stock levels
[ ] French marketplace (FR): continue expanding generic catalogue
[ ] Monitor success rate: if drops below 7%, review product selection process
```

---

## Financial Context

- Personalised products estimated at ~£16-18k/month revenue
  (revised downward from initial £26k estimate after analysis)
- At 10% success rate and £400/month per mature product:
  need ~40-45 successfully matured generic products to replace
- At current ~7-8% success rate: need ~50-55 successful products
- With 256 products/month publish rate (if sustained):
  replacement revenue achievable within 12 months
- Revenue gap during transition: manageable if generic publishing
  rate is maintained and price ladder slows (not stops) personalised decline

---

## Summary in One Paragraph

NBNE is transitioning its Amazon e-commerce operation away from
personalised products toward generic products over an 18-24 month
period. The primary driver is labour scalability — personalised
products scale 1:1 with orders while generics scale ~1:5 via batch
manufacturing and automation. The transition has three tracks:
(1) immediate shutdown of the broken black/white memorial range,
(2) a price ladder on the main personalised memorial SKU to reduce
volume while protecting the listing asset and diverting customers
to generics, and (3) sustained generic product publishing at
25-30+ products/month to build replacement revenue. The first price
increase (£19.99 → £22.99) is overdue and should be actioned now.
The manufacturing app (Deek/Manufacture) should track phase-out
status, price ladder progress, and labour time per product type
to validate the economics and flag when actions are due.
