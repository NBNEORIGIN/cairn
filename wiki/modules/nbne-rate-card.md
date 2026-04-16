# NBNE Rate Card

**Updated**: 2026-04-11
**Authoritative source** for NBNE's published rates. The `analyze_enquiry`
chat tool reads this file directly and injects it as fixed context on
every enquiry analysis so quoted rates are always current.

**Edit this file** to add or change rates. Commit to `NBNEORIGIN/deek`
main — the Hetzner deek-api cron pulls the repo every few hours and
rebuilds, so changes propagate automatically.

---

## Labour & design

| Service | Rate | Unit |
|---|---|---|
| **Graphic design** | £40.00 | per hour, ex VAT |
| **Labour** (install, fabrication, production) | £40.00 | per hour, ex VAT |
| **Labour at height** (see rules below) | 3 × £40.00 + equipment | — |

Standard hourly rate for any design or labour time billed on a job.
Minimum billing increment is 1 hour unless explicitly agreed otherwise
with the client.

### Labour-at-height rules

Any install involving work above ground-level reach (fascia, shopfront
letters on brackets, pole-mounted signs, roof-level wayfinding,
overhead gantry, etc.) incurs the following surcharges over the
standard £40/hr rate:

1. **Minimum three personnel on site**: one groundsman + two
   operatives. Hours bill at **3 × £40/hr = £120/hr** for the
   duration of the at-height install window.
2. **Risk assessment time**: non-trivial — typically 1–2 hours of
   planning time pre-visit, billed at the standard £40/hr rate.
3. **Access equipment**:
   - Towers / ladders that NBNE owns: no charge beyond labour
   - **Scaffold hire**: charged at cost + reasonable admin, flag to
     client as a line item on the quote
   - **MEWP / cherry picker hire**: charged at cost + reasonable
     admin, flag as a separate line item — typical day hire is
     £180–£350/day depending on reach
   - Minimum 1-day hire for most access equipment

**When the analyzer should raise this:** any enquiry mentioning
fascia, shopfront letters, pole-mounted signs, first-floor or
higher installation, overhead signage, or any site where the
access can't reasonably be done from a single standing ladder.
Raise it proactively as a cost driver — clients are frequently
unaware of the real install cost for at-height work, and
surfacing it early prevents nasty surprises at quote-review time.

---

## A-frames / pavement signs

| Item | Rate | Unit | Notes |
|---|---|---|---|
| **A-frame pavement swinger, 700mm wide** | **£120** | each, ex VAT | Stand-only reference price — **add graphic design + print** |
| **Basic wooden A-frame** | **£120** | each, ex VAT | Same rate as swinger — **add graphic design + print** |
| Replacement printed insert for existing frame | ~£45 | each, ex VAT | Guide price (e.g. Debbie Potter / The Serviceman, April 2026) |
| Replacement printed set (double-sided) | ~£90 | per set of 2, ex VAT | |

Typical cheap-and-fast quote shape for a pub / shop with an existing
frame: £45 per panel, £90 for a double-sided pair, 5–7 working days
from artwork sign-off.

---

## Printed panels — industry reference pricing (per m², ex VAT)

**⚠️ These are UK industry reference prices from online research, NOT
NBNE's own published rates.** NBNE is in NE England where prices tend
to run **lower than the UK average**, and these figures **exclude
graphic design and labour** — those are billed separately at the
£40/hr rate above. Use these as a *ceiling* when benchmarking against
quotes: if a competitor quotes at the top of this range and NBNE
undercuts, the margin story is easy to defend.

| Material | 3mm–5mm thickness | 3mm | 3mm–10mm | Notes |
|---|---|---|---|---|
| **Foamex (PVC foam board)** | **£18–£35/m²** | — | — | Indoor / short-term outdoor |
| **Aluminium Composite (Dibond / ACM)** | — | **£30–£60+/m²** | — | Durable, outdoor, long-term |
| **Acrylic (Perspex)** | — | — | **£50–£100+/m²** | High-end photo / display |
| **Exhibition panels (shell scheme / PVC)** | £18–£25/m² | — | — | For large exhibition runs |

**How the analyzer should use these:**
- Quote the *industry-reference ceiling* when explaining material
  cost rationale to a client
- Always note that NBNE's actual rate is typically below the UK range
- Add labour + design hours (billed at £40/hr) on top
- For firm pricing, the analyzer should flag "ask Toby for a firm
  quote on {material} {size}" rather than guessing within the range

---

## Fascia & shopfront

| Item | Rate | Unit | Notes |
|---|---|---|---|
| Low-spec fascia (flexiface, trough light) | _TBC_ | from | |
| Mid-spec fascia (aluminium tray + vinyl) | ~£1,928 | from, ex VAT | Historical ref, `wiki/modules/fascia-sign-installation-nbne-standard-options-and-process.md` |
| High-spec fascia (illuminated ACM, built-up letters) | ~£4,730 | from, ex VAT | Historical ref, same source |
| Trough lighting (add-on, installed) | ~£700–£800 | installed | Ex VAT |

---

## Interior signage & wayfinding

| Item | Rate | Unit | Notes |
|---|---|---|---|
| Interior wayfinding (basic, printed) | ~£1,285 | from | Ex VAT, historical ref |
| Acrylic dimensional wayfinding | _TBC_ | from | |

---

## Standard turnaround

| Product | Lead time |
|---|---|
| Printed panel for existing A-board | 5–7 working days from artwork sign-off |
| Complete new A-frame + print | 5–7 working days from artwork sign-off |
| Complete new pavement sign | 7–10 working days from artwork sign-off |
| Fascia sign (low/mid spec) | 3–4 weeks typical, longer if planning consent required |
| Fascia sign (high spec / illuminated) | 5–6 weeks typical |

---

## Usage rules for the analyzer

When `analyze_enquiry` cites a rate from this file, it should:

1. Quote the rate **ex VAT**
2. Reference this file as the source (`wiki/modules/nbne-rate-card.md`)
3. Note if the rate is a **benchmark / guide price** vs a **firm fixed price**
4. Add the **design-hour caveat** whenever artwork is likely to be needed
5. **Never invent a rate that isn't in this file** — if a rate is _TBC_
   or missing, the action should be "ask Toby for a firm quote on X"
   rather than guessing
6. For the industry-reference per-m² panel prices, always note they are
   a **UK ceiling** and NBNE tends to run **below** the range

---

## Open items — rates to confirm with Toby

- Printed panel exact per-m² rates at NBNE (not the UK ceiling)
- Low-spec fascia starting price (flexiface + trough)
- Interior acrylic dimensional rate
- Standard install call-out fee
- Minimum order value
- Rush / expedite surcharge policy
- Van mileage / delivery charges for out-of-area jobs
