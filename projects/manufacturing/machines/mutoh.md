---
id: mutoh
nickname: Mutoh
brand: Mutoh Industries Ltd (Japan)
manufacturer: Mutoh Industries Co., Ltd, Japan (built in Japan)
distributor: Mutoh Europe NV (EMEA business unit)
model: XpertJet 461UF
model_code: XPJ-461UF
niche: A3+ desktop UV-LED flatbed printer — rigid / semi-rigid small-format
stream: printing
status: live-lease
ownership: LEASED — see mutoh-lease.md (commercially sensitive)
year_acquired: TBD
print_area_mm: 483 × 329 (A3+, 19" × 13")
max_object_thickness_mm:
  - 150 mm with standard table removed (8 kg max)
  - 70 mm with standard table installed (4 kg max)
  - 70 mm with optional vacuum table (4 kg max)
print_head: single Epson DX7 micro-piezo
nozzles: 1440 (8 lines × 180 nozzles)
native_resolution_dpi: 360 per nozzle line / 1440 addressable
droplet_size_pl_min: 1.5
droplet_size_pl_max: 21
firing_frequency_khz: 8
ink_chemistries:
  - UH21 (rigid LED-UV ink, Mutoh genuine)
  - US11 (flexible LED-UV ink, Mutoh genuine)
ink_colours: CMYK + White + Varnish
ink_configurations:
  - 2× CMYK (higher print speed)
  - CMYK + 2× White + 2× Varnish (full feature set)
cartridge_size_ml: 220
white_ink_circulation: yes (anti-sedimentation system)
uv_lamp: segmented 2-inch UV-LED, 6 individually controllable sections (Mutoh Local Dimming Control Technology)
display: OLED touchscreen
remote_monitoring: Mutoh Status Monitor (smartphone/tablet)
software_bundled:
  - VerteLith RIP (Mutoh genuine)
  - FlexiDESIGN MUTOH Edition
  - Mutoh Layer Editor (white/varnish layer control)
  - Standard Windows printer driver
substrate_compatibility:
  - ABS, ACM, glass, PC, PET, extruded acrylic
  - PP, PS, foam, PVC, Tyvek
  - wood, leather, coated metal
  - (adhesion may require primer for glass / acrylic / PP — see tips)
features:
  - automatic table lift with obstacle detection laser
  - LED pointer for media positioning / origin setting
  - automatic media thickness measurement
  - print resume after interruption
  - Mutoh Intelligent Interweaving (i-weave)
  - selected active nozzle blocks (waste reduction)
factory_warranty: per lease terms (TBD)
location:
serial:
purchased:
primary_user:
technical_owner:
notes: |
  NBNE's small-format UV-LED flatbed printer. Sits in the niche
  between the larger Refine Color flatbeds (Rolf, Mao, Mimaki) and
  desktop print work. Best suited for: personalised small items,
  prototypes, sample prints, awards, signage components, items
  needing varnish / gloss effects, items needing white ink underbase
  on dark or clear substrates.

  NOT used for: full-sheet production work (goes to Rolf or Mimaki),
  roll-to-roll work (goes to Roland), high-volume identical work
  (uneconomic at this scale).

  XPJ-461UF was launched by Mutoh Europe in late 2021 — NBNE's
  specific machine likely dates from 2022-2024 given lease timing
  (confirm exact year from lease handover paperwork).

  PRINT-HEAD SINGLE-POINT-OF-FAILURE: the DX7 head is the dominant
  consumable risk. £1k-£2k+ to replace OEM, longer for third-party.
  Treat the daily nozzle check as the equivalent of the Beast's
  optic check — non-negotiable, gates all work.

  WHITE INK SECONDARY RISK: heavier than carrier, settles even with
  the circulation system. Streaky white = sediment. Don't leave it
  sitting unused for >24 hours without an agitation print. Shorter
  shelf-life than CMYK; plan ordering accordingly.

  LEASE IMPLICATIONS pervade decisions on this machine — ink
  procurement, service routing, modification, even physical
  relocation are all constrained by the lease contract. Default
  posture: Mutoh dealer (Grafityp UK) first, in-house intervention
  only with written lessor approval. See mutoh-lease.md for full
  detail.
aliases:
  - mutoh
  - the mutoh
  - mutoh 461
  - xpj-461uf
  - xpertjet
  - 461uf
  - the uv printer
  - small-format uv
  - desktop uv
  - mutoh flatbed
manuals_path: /opt/nbne/manuals/Mutoh/
ratified: 2026-04-30
research_dossier: 2026-05-01 (Toby + chat-Claude — Layers 2/3/5/6 + Lease ingested)
---

# Mutoh — XpertJet 461UF UV-LED flatbed printer

The Mutoh is NBNE's small-format UV-LED flatbed printer: an Epson
DX7 single-head A3+ machine with white + varnish capability and
Mutoh's own RIP (VerteLith), Layer Editor, and Status Monitor
software stack. Built in Japan by Mutoh Industries, distributed
through Mutoh Europe NV; leased rather than owned, supplied through
Grafityp UK or similar Mutoh-authorised dealer.

The 1.5pl minimum droplet, segmented UV-LED with Local Dimming
Control, white ink circulation, and obstacle-detection laser put it
above hobby-tier UV flatbeds. The lease + small bed put it below
production-tier flatbeds. Niche fit: small-format UV jobs that
benefit from white / varnish capability — prototypes, samples,
awards, personalisation, signage components — without competing
with Rolf or Mimaki for full-sheet rigid work.

Common-noun risk: "Mutoh" is unambiguous as a brand. No collision.

## Manual coverage

Layer 2/3/5/6 + Lease ingested 2026-05-01 from the chat-Claude
research dossier:
- `mutoh-manuals-index.md` — catalogue of OEM service manuals
  already on Drive at `001 NBNE / 002 BLANKS / 017 MUTOH` plus the
  user/operator + RIP + ink-MSDS docs still to source
- `mutoh-procedures.md` — daily start-up / nozzle check / shift
  routine + weekly + monthly maintenance + critical operating rules
- `mutoh-lease.md` — lease implications, what to find out from the
  contract, ink-procurement constraints, modification restrictions,
  end-of-term return prep. Commercially sensitive
- `mutoh-supply-chain.md` — UH21 / US11 ink, cleaning consumables,
  print-head replacement economics, UK suppliers, lead times
- `mutoh-tips.md` — operator wisdom: print-head as single point of
  failure, white-ink sedimentation, varnish settings, substrate-
  by-substrate adhesion, RIP profile preservation, environmental
  factors, lease-specific ops habits

Searchable via `search_manuals(query=..., machine="Mutoh")`.

## Maintenance log

_Per-event entries to be appended over time, dated. The
mutoh-tips file is the dated append-only home for operator
lessons; this is for machine-specific maintenance events
(head replacement, lamp module replacement, dampers, encoder strip,
service visits)._

## Open gaps — to fill from machine + lease paperwork

1. **Serial number** — rear of machine, manufacturer's plate
2. **Year of manufacture / acquisition by NBNE** — lease handover paperwork
3. **Lease counterparty** — finance company name, contract reference, monthly cost, contract end date. **HIGHEST PRIORITY** — without this, every other Mutoh decision has uncertain risk
4. **Lease service inclusions** — what's covered, what isn't. Same priority as #3
5. **Original supplying dealer** — likely Grafityp UK; confirm
6. **Current ink chemistry** — UH21 (rigid), US11 (flexible), or both
7. **UV lamp hours** — visible on touchscreen system info
8. **Last service visit date + what was done**
9. **Any logged issues since acquisition** — jams, head replacements, substrate damages
10. **Workshop environment data** — typical temperature/humidity range, dust exposure
11. **VerteLith RIP version + saved profile library** — same logic as Hulk's post-processor: irreplaceable configuration that walks out the door if the workshop PC dies. **URGENT — back up to Drive AND ingest into Deek**
12. **Primary user / technical owner** — who runs day-to-day, who calls Grafityp when something's wrong

Highest-priority items: **#3 + #4 (lease terms)** unblock all
Mutoh decisions; **#11 (RIP profile backup)** is the one-shot data-
loss risk; **#7 + #8 (lamp hours, last service)** dictate when the
next service is due.

## Tribal knowledge

Same advice as the Hulk: half an hour with whoever runs the Mutoh
day-to-day (TBD), recorded, transcribed, ingested. Captures what
the service manuals can't tell you about THIS specific machine in
THIS workshop with THIS substrate mix.
