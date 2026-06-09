# Frontend API (Ledgerline UI prep)

Endpoints added for React UI integration. All responses use `{ data, error, meta }`.

## Settings (read-only)

`GET /api/settings` — mailbox, Graph/Blob/DI flags, ABN mode, folder names (no secrets).

## Rule book

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/rule-book` | Current `rule_book.json` |
| PUT | `/api/rule-book` | Replace file + clear mapper cache |

## Invoices

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/invoices` | List; query: `status`, `vendor`, `invoice_date_from`, `invoice_date_to`, `page`, `page_size` |
| GET | `/api/invoices/{id}/file` | Download PDF/image/DOCX |
| POST | `/api/invoices/{id}/attach` | Upload PDF when `has_stored_file` is false (then approve/reprocess) |

Invoice responses include `has_stored_file` (path set and file exists on disk or blob).

## Vendors

| Method | Path | Purpose |
|--------|------|---------|
| DELETE | `/api/vendors/{id}` | Remove registry row (204) |

## Approvals queue

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/approvals` | Invoices with `exception` or `duplicate_skipped` |
| POST | `/api/approvals/{id}/approve` | Reset to `pending` for reprocess; then `POST /api/process/trigger` |

## Dashboard

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/dashboard/stats` | KPI counters (inbox, approvals, totals, integrations, reconciliation) |
| GET | `/api/dashboard/overview?activity_limit=8` | **Preferred for UI** — stats + activity + top vendors + cash forecast + 7-day sparkline |
| GET | `/api/dashboard/activity?limit=20` | Audit log feed only |

`DashboardStats` fields: `invoices_this_month`, `inbox_count`, `pending_approval`, `total_value_aud`, `synced_percent`, `avg_processing_seconds`, `reconciliation_delta_dr_cr`, `integrations_connected`, plus legacy counts.

Existing endpoints: audit, reports, processing, reconciliation, vendors CRUD, invoice upload/reprocess.
