# Assessment brief compliance

Updates aligned with **Email-to-Accounting** candidate brief §§2–4.

## Validation (VR)

| Rule | Brief requirement | Implementation |
|------|-------------------|----------------|
| VR01 | Total = subtotal + GST | ±$0.01 tolerance |
| VR02 | Unique invoice # **per vendor** | `invoice_no` + `vendor` (case-insensitive) |
| VR03 | Required fields + line items | Header fields, `due_date`, ≥1 line with description + amount |
| VR05 | ABN or equivalent tax ID | **Test default:** `ABN_VALIDATION_MODE=format` (11 digits). **Production:** `checksum` (ATO mod-89, international tax ID, approved registry) |
| VR06 | Dates | `invoice_date` and `due_date`; due ≥ invoice |
| VR07 | AUD | Default AUD |
| VR08 | GST 10% | Header subtotal × 10% (±$0.02) |

Duplicate **files** remain pipeline `duplicate_skipped` (SHA-256), not a VR rule.

## Parsing (§3)

- Line items: local table heuristic, Azure DI `Items`, or synthetic line from subtotal.
- `po_reference`, `cost_centre`: regex (local) + DI `PurchaseOrder` / `ProjectCode`.
- Attachments: **PDF, JPG/PNG, DOCX** (email filter + upload API).

## Mapping (§4.2)

Priority unchanged: PO → vendor → keyword. PO match uses `po_reference` and `invoice_no`.

## Database

Migration `003`: `invoices.po_reference`, `invoices.cost_centre`, `line_items.tax_amount`.

Apply migrations:

```powershell
cd backend && alembic upgrade head
# or: docker compose exec api alembic upgrade head
```

## Vendor registry

AWS and Meta seed entries include valid AU ABNs for VR05 when PDF OCR is wrong.

Reprocess exception invoices after `alembic upgrade head` and worker restart.
