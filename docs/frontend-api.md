# Frontend API (Ledgerline UI)

Endpoints used by the React app. All responses use `{ data, error, meta }`. Authenticated routes require `Authorization: Bearer <token>` when `AUTH_REQUIRED=true`.

## Auth

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/login` | Email/password → JWT |
| POST | `/api/auth/register` | New org + admin user |
| GET | `/api/auth/me` | Current user |
| POST | `/api/auth/switch-org` | Change active organisation |
| POST | `/api/auth/refresh` | Refresh session |

## Settings

`GET /api/settings` — mailbox, Graph/Blob/DI/Postgres/Redis flags, ABN mode, folder names (no secrets).

## Rule book

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/rule-book/config` | Org rule book JSON (v4 schema + masters) |
| PUT | `/api/rule-book/config` | Save config (**admin**); writes audit `rule_book_updated` |
| POST | `/api/rule-book/evaluate` | Rule evaluation preview (API; not shown in UI) |
| GET | `/api/rule-book/changelog` | Recent rule saves and remaps |
| POST | `/api/invoices/remap` | Re-apply rules to invoices (**admin**) |

Master data (also surfaced on Rule Book tabs):

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST/PATCH/DELETE | `/api/vendor-masters` | Vendor master CRUD (**writes: admin**) |
| GET/POST/PATCH/DELETE | `/api/employee-masters` | Employee master CRUD (**writes: admin**) |
| GET/POST | `/api/pending-vendors` | Pending vendor queue |
| POST | `/api/pending-vendors/{id}/promote` | Promote → release held invoices |

## Invoices

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/invoices` | List; query: `status`, `route_target`, `vendor`, dates, `page`, `page_size` |
| GET | `/api/invoices/{id}` | Detail + line items + journals |
| PATCH | `/api/invoices/{id}` | Edit fields / line items |
| GET | `/api/invoices/{id}/file` | Download PDF/image |
| GET | `/api/invoices/{id}/pipeline` | Pipeline audit steps |
| POST | `/api/invoices/upload` | Upload new document |
| POST | `/api/invoices/{id}/attach` | Attach file to existing row |
| POST | `/api/invoices/{id}/reprocess` | Reset and re-run pipeline |
| POST | `/api/invoices/{id}/publish` | Ledger publish hook |

Invoice fields include `route_target`, `evaluation_status`, `matched_rule_ids`, `vendor_confidence`, `has_stored_file`.

## Approvals

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/approvals` | Exception / duplicate / review queue |
| POST | `/api/approvals/{id}/approve` | Approve → reprocess |
| POST | `/api/approvals/{id}/reject` | Reject |
| POST | `/api/approvals/{id}/request` | Request approval |
| DELETE | `/api/approvals/{id}` | Permanent delete |

## Dashboard

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/dashboard/badges` | Nav badge counts (inbox, approvals, team expenses, payments) |
| GET | `/api/dashboard/overview` | **Preferred** — stats + activity + vendors + forecast + sparkline |
| GET | `/api/dashboard/stats` | KPI counters only |
| GET | `/api/dashboard/activity` | Audit feed |

## Processing

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/process/trigger` | Poll Graph inbox / process pending |
| GET | `/api/process/status` | Worker state |

## Other

| Area | Base path |
|------|-----------|
| Vendors (registry) | `/api/vendors` |
| Vault | `/api/vault/tree`, `/api/vault/migrate` |
| Matrix | `/api/matrix` |
| Reconciliation | `/api/reconciliation/overview`, `/api/reconciliation/daily` |
| Reports | `/api/reports/analytics`, `/api/reports/documents`, `/api/reports/download` |
| Approval policy | `/api/approval-policy` |
| Audit log (org-scoped) | `/api/audit-log` |
| Mailboxes | `/api/mailboxes` |
| Organisations | `/api/organisations` |

See also [docs/azure-env-mapping.md](azure-env-mapping.md) for integration env vars.
