# Phase 7 — Rule book completion & page routing

Phase 7 closes the remaining backend rule book gaps and maps all four route targets to UI surfaces.

## Backend

| Change | Module |
|--------|--------|
| Team expense rules map to GL (`post_to.ledger`) | `rule_book_mapper.py` — purchase → **team** → expense → vendor → fallback |
| Email capture respects rule `mailbox` | `rule_engine.match_email_capture_rule` + ingest capture |
| Employee `mtd_spent` / `ytd_spent` updated on processed team invoices | `team_expense_service.record_team_expense_processed` in pipeline |
| Removed duplicate `is_fallback_mapping` in pipeline | Uses `rule_book_mapper.is_fallback_mapping` |

## Frontend

| Route target | Page |
|--------------|------|
| Purchase Management | `/purchases` — `RoutedInvoicesPanel` |
| Expenses Management | Inbox / API only (no dedicated page) |
| Team Expenses | `/team-expenses` — `RoutedInvoicesPanel` |
| Vault | `/vault` — folder tree, files, document sets |

Matrix flags prefer live `evaluation_status` over mock data when available.

## Deploy

After pull:

```powershell
cd backend
alembic upgrade head
pytest -q
```

## Not in Phase 7 (future)

- Replacing Purchase/Team mock PO/claim tables with full API models
- Renaming `v4*` frontend type files (cosmetic)
- Upload path ingest routing (no email metadata on manual upload)
