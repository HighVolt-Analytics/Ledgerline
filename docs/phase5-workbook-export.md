# Phase 5 — Excel workbook export

After invoices are **processed**, the pipeline writes a multi-sheet workbook matching `output_workbook.xlsx`.

## Sheets

| Tab | Content |
|-----|---------|
| README | Workflow description |
| Invoices | Header fields + validation status |
| Line Items | Per-line amounts (DB lines or 50/50 split estimate) |
| Ledger Mapping | PO → Vendor → Keyword → Suspense per line |
| Journal Entries | Expense, GST Paid, Accounts Payable |
| Daily Reconciliation | RC1/RC2 per invoice date |
| Expense Summary | Totals by ledger account (ex-GST) |
| Processing Status | Pipeline stage checkmarks |
| Rule Book | Contents of `rule_book.json` |

## Output location

- Local: `{UPLOAD_DIR}/reports/output_workbook.xlsx` (all dates), `output_workbook_{date}.xlsx` (single day), or `output_workbook_{from}_to_{to}.xlsx` (range)
- Azure Blob (when configured): same filenames under `reports/`

## API

```powershell
# All invoices
Invoke-RestMethod -Method POST "http://localhost:8001/api/reports/generate"

# Single day (legacy)
Invoke-RestMethod -Method POST "http://localhost:8001/api/reports/generate?workbook_date=2026-05-06"

# Inclusive date range
Invoke-RestMethod -Method POST "http://localhost:8001/api/reports/generate?date_from=2026-05-01&date_to=2026-05-31"

# Download (same query params as generate)
Invoke-WebRequest -Uri "http://localhost:8001/api/reports/download?date_from=2026-05-01&date_to=2026-05-31" -OutFile output.xlsx
```

Automatic export runs at the end of `process_invoice` when status becomes `processed`.

## Audit events

- `workbook_exported` — success
- `workbook_export_failed` — export error (invoice still processed)
