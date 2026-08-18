# Foremost EG ERP — Phase 2 / 3 Roadmap

Phase 1 (shipped) runs the plant end-to-end: RBAC, master data, dynamic
attributes, quotation→invoice→job order→reserve/issue→production→FG→delivery,
coil traceability, immutable inventory ledger, audit/status history, dashboards
and reports. This document plans the next phases and notes the schema hooks that
are **already in place** so Phase 2 is mostly logic, not migrations.

## Phase 2 — Operational

| Area | Work | Existing hook |
|------|------|---------------|
| Credit rules | Customer credit-limit checks, AR aging, blocking rules | `Customer.credit_limit`, `PaymentTerm`, `CreditCheckLog`, `AppSetting['credit.*']` |
| Price matrices | Effective-dated matrices + customer price lists resolved onto quote lines | `PriceList`, `PriceListVersion`, `PriceMatrixRow(keys JSON)` |
| Full BOM & formulas | Multi-component BOM, formula engine, estimated-vs-actual variance | `JobMaterialRequirement.estimated_qty/actual_qty`, `services.resolve_raw_item`, `ProductConstraint` — add `BOMHeader`/`BOMLine`/`MaterialFormula` |
| QC module | Inspection queue, hold/reject, quarantine gating FG receipt | `QCInspection`, `FGLotStatus.QUARANTINE` |
| Warehouse transfers | Transfer orders + in-transit | `StockTransfer` model + ledger `TRANSFER` type |
| Remnant split | Auto-create remnant coil below threshold | `Coil.parent_coil`, `CoilConsumption.remnant_coil`, `AppSetting['coil.remnant_threshold_m']` |
| Purchasing / MRP-lite | Reorder suggestions from `material_short`, PO to supplier | `JobOrder.material_short`, `Item.reorder_point`, `Supplier` |
| Production reports | Alias-based LM by profile/gauge/color matching the Jan–May Excel | `ProfileAlias(context='production_report')`, `ProductionRunOutput`, `CoilConsumption` |
| Maker-checker everywhere | Extend `approval.maker_checker` beyond quote/invoice | `AppSetting`, generic approval pattern |

## Phase 3 — Advanced

- Scheduling & machine capacity (`Machine`, `ProductionRun` timestamps).
- Costing / job profitability (coil `cost`, `standard_cost`, consumption ledger).
- Margin & management dashboards (extend `reports/`).
- Barcode / QR for coils and FG lots (`Coil.coil_number`, `FinishedGoodsLot.lot_number`).
- Customer portal for quotation acceptance (`CustomerAcceptance`).
- Multi-plant operations (`Warehouse.is_plant`, per-plant machines) and integrations.

## Open business questions (Section T) — encoded as configurable defaults

These are live in **Master Data → System Settings** (`AppSetting`), not hard-coded,
so stakeholders can change them without a release:

- `credit.gate_mode` (none/deposit/full) + `credit.deposit_pct`
- `fg.always_post`, `approval.maker_checker`
- `material.default_waste_pct`, `coil.remnant_threshold_m`
- `production.overproduction_tolerance_pct`, `quotation.default_validity_days`
- `company.*`, `tax.default_rate_pct`

Still to confirm with the company and then lock in settings/master data: fiscal
(BIR) invoice numbering, exact 5-Rib/8-Rib ↔ commercial profile mapping, drawing
verification owner + SLA, coil costing method, and whether Phase 1 must reproduce
the Jan–May production Excel formats exactly.
