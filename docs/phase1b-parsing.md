# Phase 1b — Invoice PDF parsing

Email ingestion (Phase 1) saves PDFs; this phase extracts structured fields before validation.

## Strategy

1. **Local** — `pdfplumber` → `PyMuPDF` text extraction, then regex field mapping.
2. **Fallback** — Azure Document Intelligence **`prebuilt-invoice`** when:
   - Extracted text is shorter than `PARSE_MIN_TEXT_CHARS` (default 200), or
   - Local parse is missing required fields or fails sanity checks (e.g. bad invoice number).

If `AZURE_DI_ENDPOINT` / `AZURE_DI_KEY` are empty, only local parsing runs.

## Configuration (`backend/.env`)

```env
AZURE_DI_ENDPOINT=https://<resource>.cognitiveservices.azure.com/
AZURE_DI_KEY=<key>
AZURE_DI_MODEL_ID=prebuilt-invoice
PARSE_MIN_TEXT_CHARS=200
```

Create a **Document Intelligence** resource in Azure Portal (no full resource group required for dev).

## Audit events

After a successful parse, the pipeline logs:

- `parse_completed` — `source`: `local` | `azure_di`, `confidence`: `high` | `low`

## Test without email

```powershell
# Upload PDF (Swagger or curl)
POST http://localhost:8001/api/invoices/upload

# Run pipeline (use separate lines — do not paste commands together)
docker compose restart worker
Invoke-RestMethod -Method POST http://localhost:8001/api/process/trigger

# Re-run parser on an existing invoice (exception / duplicate_skipped)
Invoke-RestMethod -Method POST http://localhost:8001/api/invoices/43/reprocess
Invoke-RestMethod -Method POST http://localhost:8001/api/process/trigger

# Check parse source
Invoke-RestMethod "http://localhost:8001/api/audit-log?event=parse_completed"
```

## Tests

```bash
cd backend && pytest tests/test_pdf_parser.py -v
```
