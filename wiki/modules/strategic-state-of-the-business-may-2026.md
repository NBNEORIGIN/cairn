# Strategic State of the Business — May 2026

## Strategic State of the Business — May 2026

*First defensible full-estate margin picture. Recorded 2026-05-13 following completion of COGS analysis across 1,000+ products.*

---

### Context

In May 2026, NBNE completed a significant COGS analysis exercise covering the full product estate — over 1,000 SKUs/ASINs/M-Numbers. The analysis factored in:
- Time taken to manufacture specific product types
- Material costs and wastage rates
- Labour and overhead allocation

This was not a trivial exercise. The resulting figures carry some uncertainty (acknowledged by Toby at time of writing), but the directional conclusions are robust and defensible even if individual line-item precision improves over time.

Concurrently, the manufacturing app was updated to pull sales data from eBay and Etsy in addition to Amazon, giving the first complete multi-channel sales picture.

---

### Finding 1: Personalised Product Phase-Out Is Confirmed Correct

The economics are now quantified, not assumed. Personalised products struggle to break even at scale because:
- Labour scales 1:1 with units (no economies of scale)
- Per-unit production time is materially higher than generic equivalents
- Amazon fee structures compress margin further on lower-priced personalised lines

**Decision:** Continue phasing out personalised SKUs. This is not a commercial retreat — it is a capital reallocation toward products with genuine margin.

**Active action outstanding:** Price ladder review on B07J3HDB2Y (currently £19.99, target £22.99) remains the most immediately actionable lever.

*See also: `wiki/modules/au-marketplace-no-personalised-products-policy.md` — AU marketplace never listed personalised products; confirmed by data 2026-05-13.*

---

### Finding 2: Generic Products Have Higher Margin Than Expected

Even accounting for likely COGS underestimation, generic product margins are materially better than previously believed. The key insight is the **direction of error**: if COGS are underestimated and margins are still healthy, the floor is higher than feared.

**Implication:** Generic product lines are the core engine of the e-commerce business. Investment in content quality, traffic, and conversion (not production capacity) is the primary lever for this category.

**Next step:** Stress-test the largest generic lines once COGS confidence improves. Identify the top 10 by revenue and confirm margin at that level.

---

### Finding 3: B2B Signage Margin Requires Closer Measurement

B2B commercial signage *feels* high-margin — high per-job revenue, skilled work, strong customer relationships. However, the true margin per hour may be lower than assumed once the following are properly allocated:
- Quoting and pre-sales time
- Installation and travel
- Job-specific materials and waste
- Non-billable revision cycles

**Current status:** Not yet measured at job level. This requires a Ledger-level analysis — job by job, not category-level averages.

**Caution:** Do not make strategic decisions that deprioritise B2B based on this finding alone. The finding is "we don't know accurately enough" — not "B2B is low margin." Measure before concluding.

---

### Finding 4: Phloe SaaS Contribution Is Currently Unknown

Phloe (multi-tenant booking/scheduling SaaS) has several live deployments as of May 2026:
- DemNurse (demnurse.nbne.uk)
- Ganbarukai
- Amble Pin Cushion
- NAPCO Pizza
- Proving Ground demo estate

Current advertising: local social media only. No paid acquisition. No formal pricing page or inbound funnel.

**Revenue contribution:** Unknown / not yet measured against cost base. Cost base is low (Hetzner hosting, internal development time).

**Key unknowns:**
- Which deployments are generating recurring licence fees vs. goodwill/trial installs
- Total addressable market if marketed properly
- Margin profile vs. Amazon e-commerce and B2B signage

**Implication:** Phloe is an optionality play at this stage. The cost of maintaining it is low; the upside if properly marketed is potentially significant relative to the current revenue base. Measuring it properly is a prerequisite for any strategic decision about investment or marketing spend.

---

### Summary Table (May 2026)

| Business Line | Margin Confidence | Direction | Next Action |
|---|---|---|---|
| Amazon Generic | Medium (COGS ~right) | ✅ Better than expected | Stress-test top 10 lines |
| Amazon Personalised | High | ❌ Phase out confirmed | Continue phase-out |
| B2B Signage | Low | ⚠️ Needs measurement | Ledger job-level analysis |
| Phloe SaaS | Very low | ❓ Unknown | Measure recurring fees; define TAM |
| eBay / Etsy | Very low | ❓ New data feed live | Monitor as data accumulates |

---

### Notes on Data Quality

- COGS figures as of May 2026 are first-generation estimates. They are directionally correct but will improve with iteration.
- eBay and Etsy sales data integration into the manufacturing app is newly live (May 2026). Multi-channel picture will sharpen over coming weeks.
- Amazon COGS are the most mature data set; B2B job-level margin is the least mature.

---

*Recorded by Deek, 2026-05-13. Source: Toby Fletcher's strategic review following full COGS analysis exercise.*

_tags: strategy, margin, cogs, state-of-business, may-2026, personalised, generic, b2b, phloe, amazon_

---
_drafted by Deek via write_wiki tool_