---
id: rolf
nickname: Rolf
brand: Refinecolor
brand_full_name: Refine Color Technology Co., Ltd
manufacturer: Refine Color Technology Co., Ltd, Dongguan, China
factory_size_sqm: 4000
manufacturer_origin_year: 2008
distributor_uk: NONE — direct-to-factory only (first NBNE machine with no UK service relationship at all)
distributor_us: Refinecolor USA (Davenport, Florida)
model: RF-6090 PRO (most likely variant — confirm at machine)
model_class: A1 desktop UV-LED flatbed printer for direct-to-object printing on rigid substrates
sub_variant_candidates:
  - RF-6090 (base model)
  - RF-6090 PRO (negative pressure ink system, silent rail, Hosonsoft N10 mainboard) — likely
  - RF-6090 GY (3-head F1080 — NOT this; Rolf has i1600)
  - RF-6090S (3× F1080 + vacuum table — NOT this; Rolf has i1600)
  - RF-6090 Ultra (i1600/i3200 + Hosonsoft visual positioning, 2025+) — possible if recent acquisition
likely_variant: RF-6090 PRO — i1600 heads + negative pressure + auto moisturising + auto timing cleaning + vacuum bed + dual UV lamps matches PRO spec; confirm at machine
niche: A1 UV-LED flatbed for direct-to-object printing — primary larger-format rigid UV workhorse alongside Mao
stream: printing
status: live (NOT EOL — Mimaki is the EOL one)
ownership: TBD — likely owned outright (Chinese imports rarely UK-finance-leased)
year_acquired: TBD (~2024 based on i1600-head era)
print_area_mm: 600 × 900 (24" × 36" — A1)
max_object_thickness_mm: 120 (one-button-adjustable)
print_resolution_max_dpi: 720 × 3600 (with i1600 heads)
print_heads: 3 × Epson i1600-U1 (1600 nozzles each, 4 rows × 400 nozzles per head)
print_head_configuration_NBNE:
  - Head 1 — CMYK colour (i1600-U1, 4-channel UV) — ACTIVE
  - Head 2 — White (i1600-U1, dedicated white) — ACTIVE
  - Head 3 — Varnish (i1600-U1) — BLOCKED, UNUSED. See rolf-varnish-head-status.md
print_head_lifespan_typical: 12-18 months under UV (community wisdom: plan for 12)
print_head_replaceable: yes — aftermarket Epson i1600-U1 ~$300-500/head, multiple global sources
ink_chemistry: UV-LED curable
ink_colours_active: CMYK + White
ink_colours_inactive: Varnish (head blocked)
ink_circulation: yes (big-bottle circulation system)
ink_supply: continuous bulk (typically 500ml-1L bottles, negative-pressure on PRO)
uv_lamps: 2 × adjustable-power UV-LED (independent control for different speeds + substrates)
auto_moisturising_system: yes — community-contested; some operators believe it ACCELERATES head wear; see rolf-tips.md
auto_timing_cleaning: yes (operator-configurable interval, RIPrint setting)
auto_height_adjustment: yes (infrared sensor)
mainboard: Hosonsoft (likely N10 on PRO variant — confirm)
software_bundled:
  - RIPrint (RIPrint.exe + Printexp.exe)
  - Newest version is dongle-free; older versions used USB Keydog dongles
software_alternative_RIPs: limited / unclear — RIPrint is proprietary; whether VersaWorks / RasterLink / VerteLith files can drive Rolf is uncertain (community-flagged concern)
control_panel: integrated touchscreen on machine
table: vacuum bed
weight_kg: ~131 (3-4 people to move; pallet truck or forklift recommended)
factory_warranty: typically 12 months from Refinecolor (likely expired given installation date)
location:
serial:
purchased:
primary_user:
technical_owner:
notes: |
  NBNE's primary larger-format UV flatbed and the centre of the
  print room's rigid-substrate workflow. Used for: ACM/Dibond
  panels, foam board, acrylic, MDF, signage components,
  personalised promotional items requiring full CMYK + white
  underbase, larger awards and recognition products.

  The dual-active-head configuration (CMYK + White) gives Rolf
  the ability to print white as a separate pass — essential for
  printing on dark, clear, or coloured substrates. This is
  Rolf's primary value over the smaller flatbeds (Mao, Mutoh,
  Mimaki).

  NOT used for: roll-to-roll work (Roland), small precision
  items where Mao or Mutoh are more nimble, sublimation work
  (Epson), and varnish/gloss effect work (the third head is
  blocked — see `rolf-varnish-head-status.md`).

  COMMERCIAL STRUCTURE — first NBNE machine with NO UK service
  relationship at all. Refinecolor is a Dongguan factory selling
  direct-to-factory via Alibaba and overseas warehouses (US,
  Europe, Peru, India). Support is online-only direct from China
  or via Refinecolor USA (Florida). UK service visit option:
  none. This is materially different from Hulk (Opus CNC Durham,
  70 mi south), Mutoh (Grafityp UK, authorised), Roland (Roland
  DG UK direct), Mimaki (Hybrid Services Crewe, 250 mi).

  HEAD ECONOMICS DIFFER FROM MUTOH. The Epson i1600-U1 is a
  commodity component with documented 12-18-month service life
  under UV ink, available aftermarket from many global sources
  (~$300-500/head). NBNE has 3 heads fitted; one is blocked. The
  expectation is each active head is replaced ~every 12-18
  months; community wisdom says plan for 12 not 18. This is a
  budgetable, planned consumable cost — unlike the Mutoh's
  single-DX7-as-mortal-failure-mode or the Mimaki's Mimaki-only
  specialist head.

  DOCUMENTATION REALITY: no formal OEM end-user manual exists
  the way Mutoh / Roland / Epson supply them. The shipped paper
  manual is rough; RIPrint help is built into the application;
  Refinecolor's product pages are limited spec sheets and
  marketing. **The chat-Claude research dossier compiled
  2026-04-30 IS the canonical reference for Rolf** — Layer 2
  through Layer 6 in NBNE's documentation system. No equivalent
  source exists publicly.

  Common-noun risk: "Rolf" is a human first name. The model
  code RF-6090 disambiguates. Earlier internal docs mistakenly
  called this machine a Mimaki UV or a Roland — both wrong;
  Rolf is the Refinecolor RF-6090 PRO.
aliases:
  - rolf
  - the rolf
  - refine 6090
  - refinecolor 6090
  - refine color 6090
  - rf-6090
  - rf6090
  - the big uv
  - the chinese uv
  - the 6090
  - the refine
manuals_path: /opt/nbne/manuals/Rolf/
ratified: 2026-04-30
research_dossier: 2026-05-02 (Toby + chat-Claude — Layer 2/3/5/6 + Varnish Head Status ingested)
---

# Rolf — Refinecolor RF-6090 PRO UV-LED flatbed (CMYK + White + Varnish-blocked)

The Rolf is NBNE's primary larger-format UV-LED flatbed printer:
a Refinecolor RF-6090 PRO from Dongguan, China. 600 × 900 mm
(A1) print area, three Epson i1600-U1 print heads (CMYK + White
+ Varnish-blocked), dual UV-LED lamps, vacuum bed, big-bottle
ink circulation with negative pressure (on the PRO variant),
auto moisturising + auto timing cleaning + auto height
adjustment, RIPrint software stack, Hosonsoft mainboard.

The dual-active configuration (CMYK + White) is Rolf's value
proposition over Mao / Mutoh / Mimaki — white-on-dark and
white-on-clear work goes here. The third head sits blocked,
its varnish/gloss capability dormant; reviving it is a separate
operational decision (see `rolf-varnish-head-status.md`).

NO UK support. The dossier itself is the canonical reference.

## Manual coverage

Layer 2/3/5/6 + Varnish Head Status ingested 2026-05-02 from the
chat-Claude research dossier:
- `rolf-manuals-index.md` — Refinecolor product pages (limited),
  Epson i1600-U1 official datasheet (canonical commodity-
  component spec), Hosonsoft mainboard reference, community
  knowledge sources (Signs101, Pegasus UV, Cloudray operator
  notes). Flags RIPrint installation + license + custom profile
  backup as URGENT — sixth machine on the rolling workshop-PC
  backup task.
- `rolf-varnish-head-status.md` — the inactive subsystem.
  Operational implications (don't run varnish circulation, don't
  test varnish channel, don't include varnish in print designs),
  revival economics (~$300-500 head + ink + 1-2 days downtime),
  decision framework if customer demand for varnish work
  develops.
- `rolf-procedures.md` — daily start-up + nozzle check first
  (gentle escalation; aggressive cleaning damages i1600 heads),
  end-of-shift, weekly + monthly maintenance, critical operating
  rules (no IPA on heads, no reflective substrates without
  prep, never run varnish-head cycles, no air-assist bypass).
- `rolf-supply-chain.md` — head replacement economics, daily/
  weekly consumables, periodic-replacement items, suppliers
  (Refinecolor direct/USA, Cloudray, AllPrintHeads,
  DigiPrint, Pegasus UV — none UK-based for service), lead
  times, recommended NBNE stock levels.
- `rolf-tips.md` — operator wisdom from a Signs101 thread by a
  UK operator with NBNE's exact fleet, including the
  community-contested moisturising-system concern + RIPrint
  proprietary lock-in + the auto-height infrared sensor's
  failure modes + dual-UV-lamp asymmetric cure.

Searchable via `search_manuals(query=..., machine="Rolf")`.

## Maintenance log

_Per-event entries to be appended over time, dated. Head
replacements (expect every 12-18 months per active head),
damper replacements, lamp inspections, RIPrint config changes
all live here. The varnish head's status updates also belong
here as dated entries._

## Open gaps — prioritised

### Critical (operational)

1. **Variant confirmation** — RF-6090 PRO vs Ultra vs base?
   Touchscreen system info or rear plate.
2. **Mainboard model** — Hosonsoft N10 (PRO) or other?
3. **Visual positioning system fitted?** — distinguishes Ultra
   from PRO.
4. Serial number — rear plate
5. Year of purchase / installation date
6. **Original purchase channel** — direct from Refinecolor
   China? Refinecolor USA? Through an Alibaba reseller? Sets
   the spare-parts relationship going forward.
7. **Head hours / replacement history** — has any head been
   replaced since purchase? When? Cost? By whom?
8. **Varnish head status detail** — what specifically does
   "blocked" mean? Operator's own description? Date it became
   blocked? Replacement attempted?
9. **Moisturising system configuration** — enabled? Adjustable?
   Operator's view on whether it's helping or harming?
10. **RIPrint version + license details + backup status** —
    same lesson as VerteLith / VersaWorks / Edge Print /
    RasterLink / Hulk's post-processor. **Sixth machine** on
    the rolling workshop-PC backup task — see "Cross-machine"
    section below.
11. Vacuum bed zone configuration — physical zones, control
12. UV lamp hours — visible in service info
13. Last full maintenance — when, by whom, what done
14. Primary user / technical owner

### Highest priority

**#1, #2, #3 (variant identification)** — determines which
product page applies and what features are present.
**#10 (RIPrint backup)** — same urgent task across all six
printers now; worth a single half-day workshop-PC backup
session rather than six separate ad-hoc tasks.
**#7 (head replacement history)** — sets the budget
expectation for the next 12 months (one head replacement
likely in that window).

## Tribal knowledge

Same advice as every other long-horizon machine: 30 min with
whoever runs Rolf day-to-day (TBD), recorded, transcribed,
ingested. Substrate-specific recipes, the operator's view on
the moisturising system, RIPrint workflow tricks, common
recurring problems, what the third (blocked) head was actually
trying to do before it stopped — all valuable.

## Cross-machine: workshop-PC backup task is now SIX machines

The rolling backup task list now spans:

| Machine | Configuration data on PC |
|---|---|
| Hulk | VCarve Pro post-processor + Syntec parameter file |
| Mutoh | VerteLith RIP profile library |
| Roland | VersaWorks 7 RIP profile library |
| Epson | Edge Print + ICC profile library |
| Mimaki | RasterLink profile library (URGENT — pre-EOL retirement) |
| **Rolf** | **RIPrint installation + license + custom profiles** |

Six-machine task. **Worth scheduling as a single half-day
workshop-PC backup session** with Ivan or whoever runs each
machine, rather than six separate ad-hoc tasks. Each library
is irreplaceable; lose any one to a workshop-PC failure and
weeks of operator-iteration work goes with it.

## Supplier register update

Rolf adds three new strategic suppliers, **none UK-based for
service**:

- **Refinecolor direct (China)** — OEM, parts, technical support, language friction, 4-8 week shipping
- **Refinecolor USA (Florida)** — Western-language alternative, still 4,000+ miles from Alnwick
- **Cloudray (China direct + UK eBay)** — commodity parts at shorter lead times via UK eBay
- **AllPrintHeads (Netherlands)** — i1600-U1 heads with EU stock + manufacturer warranty
- **DigiPrint Supplies (Europe)** — i1600-U1 same-day shipping if ordered before 4:30pm CET
- **Pegasus UV (Italy)** — heads with detailed operator documentation, useful even if not the supply route

NBNE's supplier-relationship register now spans:
- **YPS Newcastle** (Roland + EWS + likely Epson) — convenient, three machines
- **Hybrid Services Crewe** (Mimaki, soon-to-retire) — distant, single machine
- **Refinecolor + commodity parts suppliers** (Rolf, likely also Mao) — international, no UK service relationship at all
- Module-specific (Hulk via Opus CNC Durham; Mutoh via Grafityp; etc.)

The Rolf + Mao Refinecolor relationship is the first
"international-only" supply-chain in NBNE's machinery fleet.
Worth knowing in commercial-resilience terms — these two
machines have less safety net if something goes seriously
wrong.
