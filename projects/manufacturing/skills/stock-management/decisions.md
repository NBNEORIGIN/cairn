# Stock Management Decisions

## 2026-04-01 — Phase 0-3 implementation

- StockLevel is OneToOne with Product (not separate per-channel)
- Fields: current_stock, fba_stock, sixty_day_sales, thirty_day_sales, optimal_stock_30d, stock_deficit
- stock_deficit = max(0, optimal_stock_30d - current_stock), recalculated on save
- FBA stock tracked separately from local stock (fba_stock field)
- Stock never auto-updated: all changes require explicit confirmation
- CSV import preview/confirm workflow enforces this rule
- Seed import reads STOCK column from MASTER STOCK (floats, use int(float(v)))
- Optimal levels from ScratchPad2: 361 of 2,442 products have targets
- Make-list uses deficit > 0 filter — only 220 items need restocking
- Production order confirm-stock endpoint adds quantity to current_stock
