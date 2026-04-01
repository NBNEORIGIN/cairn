# Machine Routing Decisions

## 2026-04-01 — Phase 1 implementation

- BLANK_MACHINE_MAP in production/services/make_list.py is the canonical mapping
- 30+ blanks mapped to ROLF or MIMAKI
- Composite blanks (DICK,TOM / BUNDY-HAROLD) resolved by first word split on comma/hyphen
- ROLF handles: DONALD, SAVILLE, DICK, STALIN, JOSEPH, HARRY, AILEEN, SADDAM, LOUIS, HAROLD, BUNDY, FRED, KIM, JAVED, JIMMY, MIKHAIL, YANG, BIG DICK
- MIMAKI handles: IDI, MYRA, TOM, GARY, RICHARD, DRACULA, TED, PRINCE ANDREW, BARZAN, BABY JESUS, GERRY, SPOTTED DICK, LITTLE DICK
- 11 products remain unmapped: empty blank, N/A, HARRY+TWINE, JOSEPH ADHESIVE
- Ben's rule: "99% of the time blank determines machine, colour determines ROLF vs MIMAKI for UV"
- Workload balancing not yet implemented (deferred — Ben says quieter machine takes it)
- DIBOND PLACEMENT sheet has per-product ROLF/MIMAKI boolean flags — could refine the map further
