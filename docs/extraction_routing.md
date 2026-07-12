# Extraction routing (multi-document finance)

Classification and extraction are separate. After a document type (DT) is confirmed, the pipeline routes using **org-defined DT metadata** — not a hardcoded DT-01…DT-28 matrix.

## Pipeline stages (unchanged order)

1. Ingest / split
2. Classify OCR (`prebuilt-layout`) + LLM DT classify
3. **Route** → `route_document_for_extraction` (org metadata)
4. **Extract** via strategy (`enrich_ocr_for_route`)
5. Normalize → `FinanceDocumentNormalized` (also projected to `InvoiceData` for persistence)
6. Validate / trust / review
7. Persist / audit (`di_route_enrich`)

## How routing is decided (priority)

1. Optional classifier port (future Azure custom classifier)
2. Org **bundle roles** — `purchaseBundleRole` / `salesBundleRole` (`po` → purchase_order, `grn` → grn, `so`/`dn` → supporting)
3. Org **playbookProfile** (explicit on the DT; shipped defaults only when the org row still matches the shipped template)
4. Catalog **azure_di_profile** (`prebuilt-invoice` → invoice family, `prebuilt-receipt` → receipt)
5. Soft **title / shortTitle** hints when profiles are empty
6. `unknown` → layout + review hints

Repurposed org DTs (e.g. DT-13 renamed to packing list with empty/supporting playbook) follow the **org** playbook, not the shipped statement mapping.

## Playbook → route

| Org `playbookProfile` | Extraction route | Typical model |
|---|---|---|
| `po_goods`, `standard_transactional`, `direct_expense`, `freight_logistics`, `intercompany`, `ar_goods` | `invoice` | `prebuilt-invoice` |
| `credit_adjustment` | `credit_note` | `prebuilt-invoice` |
| `debit_note` | `debit_note` | `prebuilt-invoice` |
| `employee_claim` | `expense_claim` | `prebuilt-invoice` when allowed |
| `reconciliation` | `statement` | layout primary |
| `supporting`, `pre_transactional`, `import_dossier`, `informational`, `master_data`, `non_actionable`, `compliance_route` | `supporting_document` (or remittance/PO/GRN via title hint) | layout only / layout primary |

Note: `po_goods` means **goods invoice against a PO**, not a purchase-order document. Actual PO/GRN docs come from bundle roles or title hints.

## Strategies and layout line modes

| Strategy | Routes | Line mode | Behavior |
|---|---|---|---|
| `invoice_family` | invoice, credit/debit note | `gap_fill` | DI rows win; layout fills missing qty/price/amount on matched rows; unmatched layout rows are **not** appended |
| `receipt_or_claim` | receipt, expense_claim | `primary` (or invoice gap_fill when claim allowed) | Receipt model if configured; else layout |
| `layout_primary` | PO, GRN, statement, remittance | `primary` | Layout/table rows only — **no** fallback to leftover DI invoice rows |
| `layout_only_review` | supporting, unknown | `ignore` | Do not treat tables as commercial line items |

Skipping the invoice model is a **`skip_reason`** (e.g. `layout_primary`), not a failure.

## Normalized schema semantics

`FinanceDocumentNormalized` is route-aware:

- **document_number** — PO/GRN/remittance/statement prefer their own refs; invoice-like uses `invoice_no`
- **amount_due** — set for invoice-like + remittance; **null** for statement / PO / GRN / supporting / unknown (statement closing balance stays on `total` only)
- **tax / subtotal / due_date** — invoice-like only
- Payload keeps `invoice_fields` as a compatibility alias; prefer `semantic_fields` + `finance_document`

## Confidence metadata

All strategies (including layout-only) attach:

- `field_sources` / `field_confidence` on the OCR payload
- `finance_document.field_*` + optional `source_confidence`
- Field confidence gate checks DI/layout keys present in payload (not invoice money keys alone)

## Config

```env
AZURE_DI_MODEL_ID=prebuilt-invoice
AZURE_DI_LAYOUT_MODEL_ID=prebuilt-layout
AZURE_DI_READ_MODEL_ID=prebuilt-read
AZURE_DI_RECEIPT_MODEL_ID=          # optional
DI_FIELD_TRUST_MIN_CONFIDENCE=0.6
DI_LINE_ITEM_TRUST_MIN_CONFIDENCE=0.5
DI_RAW_PERSIST_MODE=failures       # failures | sample | always | off
DI_RAW_PERSIST_SAMPLE_RATE=0.05
DI_RAW_MAX_CHARS=500000
```

## Extraction field key resolution

LLM / merge use field **contracts** (see [`docs/extraction_fields.md`](extraction_fields.md)). Empty org `extraction_fields` does **not** mean “extract nothing” for commercial documents:

1. Explicit org `extraction_fields` / `required_fields`
2. Route-default keys for the extraction route
3. Shipped template defaults **only** when the org row still matches the shipped title/template
4. Playbook / route recommended keys
5. Commercial fallback when the route is transactional
6. Non-transactional / supporting / vault profiles stay empty unless the org configured keys

DI enrich (`enrich_ocr_for_route`) runs for **all** document AI providers when DI is enabled. Merge may use `USE_FIELD_CONTRACT_MERGE` for per-field resolution (default off = legacy layered merge).

## Extensibility

- `DocumentClassifierPort` — plug Azure custom classifier later (`classifier_port.py`).
- Strategy config supports `query_fields` and `custom_model_id` (unused until configured).

## Code entry points

- Router: `app.services.extraction.routing.route_document_for_extraction`
- Enrich: `app.services.extraction.di_extract_service.enrich_ocr_for_route`
- Normalized schema: `app.schemas.finance_document.FinanceDocumentNormalized`
