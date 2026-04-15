# CSV Import Decisions

## 2026-03-31 — Initial design

- Phase 1 uses manual CSV/TSV uploads from Seller Central (SP-API deferred to Phase 6)
- Four report types identified: FBA Manage Inventory, Sales & Traffic, Restock Inventory, Personalisation downloads (ZIP)
- Seed imports use openpyxl to read directly from Shipment_Stock_Sheet.xlsx
- Runtime imports will accept CSV/TSV uploads via the web UI
- MASTER STOCK header is at row 2 (rows 0-1 are summary rows) — parser must skip them

## 2026-04-01 — Phase 3 implementation

- Three parsers built: fba_inventory, sales_traffic, restock (in imports/parsers.py)
- Auto-detection from first CSV line column headers (detect_report_type)
- Handles both tab and comma delimited, UTF-8-BOM and Latin-1 encoding
- Multiple Amazon column name variants per report version supported
- Preview/confirm workflow: POST upload → preview changes → POST with confirm=true to apply
- SKU→M-number resolution via SKU table (many SKUs map to one product)
- Sales & Traffic aggregates units_ordered per M-number across all SKUs
- FBA Inventory updates fba_stock field only (not current_stock)
- All import actions logged to ImportLog with row counts and error details
- Personalisation downloads (ZIP) deferred to Phase 4 (D2C queue)
- Historical FBA shipments imported separately via import_fba_shipments management command (140 shipments, 42,854 units)
