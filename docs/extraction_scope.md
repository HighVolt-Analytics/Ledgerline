# Extraction scope (v1 signed-off)

## In scope

- PDF, JPG, JPEG, PNG, DOCX attachments via email/WhatsApp/Viber ingest
- Azure DI direct image ingestion (JPG/PNG) — no normalize-to-PDF step required
- File validity gate before OCR/DI
- Shape-driven line items (qty-only vs money tables)
- Citation grounding with supervisor_review on failure

## Out of scope (v1)

### Ingestion

- Email-body invoices (not attachments)
- Excel/CSV invoice submissions
- ZIP/archive multi-invoice uploads
- TIFF/HEIC unless explicitly added later
- Image normalize-to-PDF (not needed — Azure DI accepts images)

### Extraction accuracy

- `PROFILE_PACKING_LIST` playbook profile
- Line items inside `FieldFusionEngine`
- Structured `ParsedLineItem` fields (`model`, `hs_code`, `coo`)
- `tax_id` storage key unification
- New Azure `prebuilt-document` model
- Template drift detection (deferred to Sprint 5 learning loop)
- Duplicate invoice detection beyond ingest file-hash dedup
- Speculative multi-currency detection — use `tenant.default_currency` when invoice omits symbol

## Currency decision

B2B tenants are assumed single-currency-per-tenant. When `$` or other ambiguous symbols appear without ISO code, fall back to `tenant.default_currency` (audit in Sprint 0.12).

## Rotation/skew

Azure DI auto-corrects page rotation for most SKUs. Golden set includes rotated-scan fixtures for verification; no custom pre-rotation step unless golden eval fails.
