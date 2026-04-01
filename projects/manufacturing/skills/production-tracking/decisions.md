# Production Tracking Decisions

## 2026-03-31 — Initial design

- Pipeline stages match existing ORDERS sheet columns: Designed, Printed, Processed, Cut, Labelled, Packed, Shipped
- ORDERS sheet has boolean columns for each stage — production-tracking models will use the same pattern with timestamps and operator tracking added
- RECORDS sheet (2,458 rows since Dec 2023) provides historical production data that can be imported later (Phase 7)

## 2026-04-01 — Phase 1 implementation

- ProductionOrder created from make-list items via POST with m_number (not product ID)
- Default 7 stages created on order creation: designed, printed, processed, cut, labelled, packed, shipped
- Heat press and laminate stages defined in model but not auto-created (sublimation products need them added manually)
- Anonymous user support for stage advancement (no auth required — internal app)
- Stock update prompted on "packed" stage completion, requires explicit POST to confirm-stock endpoint
- Frontend uses sequential stage buttons — only the next incomplete stage is clickable
- Composite blank→machine resolution added: "DICK, TOM" → split by comma → first word "DICK" → ROLF
- 12 additional blanks added to BLANK_MACHINE_MAP (HAROLD, BUNDY, FRED, KIM, etc.)
- 11 products remain unmapped (empty blank, N/A, HARRY+TWINE, JOSEPH ADHESIVE)
