# Phase D — Governance (audit + permissions)

Implements architecture §9.3 governance: rule-change audit trail and admin-only editing.

## D.1 Rule-change audit

`PUT /api/rule-book/config` writes `rule_book_updated` to the append-only audit log with:

| Field | Content |
|-------|---------|
| `before` / `after` | Section summaries (rule counts, scalar config) |
| `changes` | Added / removed / modified rule IDs per section |
| `actor_name` / `actor_email` | Saving user |
| `client_ip` | Request IP when available |
| `org_id` | Organisation scope (column + detail) |

`POST /api/invoices/remap` (admin) writes `invoices_remapped` with `invoice_ids` of affected documents (up to 200 in audit detail).

Module: `rule_book_audit.py`, `audit_service.log_event`

## D.2 Changelog API

`GET /api/rule-book/changelog?limit=20` — recent `rule_book_updated` and `invoices_remapped` events for the current org.

UI: `RuleChangeHistory` on the Rules page.

## D.3 Role permissions

| Action | Role |
|--------|------|
| View rule book config | Any authenticated user |
| Edit rule book config | **Admin** |
| Remap invoices | **Admin** |
| Vendor / employee master writes | **Admin** |
| Rule book evaluate API | Any authenticated user |

Members see a read-only banner on the Rules page; edits are blocked in the UI and return **403** from the API.

## D.4 Audit org scoping

Migration `011` adds `audit_logs.org_id`. `GET /api/audit-log` filters to the caller's organisation.

## Verify

```powershell
cd backend
alembic upgrade head
pytest tests/test_phase_d_governance.py tests/test_rule_book_config_api.py -q

cd ..\frontend
npm run build
```

After saving a rule change as admin, open **Rule Book → Rule change history** to confirm the audit entry.
