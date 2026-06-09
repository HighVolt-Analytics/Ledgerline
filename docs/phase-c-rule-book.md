# Phase C — UI alignment (mock → API)

Connects v4 route pages and the Rule Book editor to live backend data.

## C.1 Auto-remap on rule save

When `PUT /api/rule-book/config` succeeds, the frontend calls `POST /api/invoices/remap` and:

- Invalidates invoice, nav badge, and dashboard queries
- Shows a toast when documents were re-mapped (`N documents updated`)

Module: `frontend/src/hooks/useRuleBookConfig.ts`, `RulesPage.tsx`

## C.2 Routed documents panel

`RoutedInvoicesPanel` loads invoices via `GET /api/invoices?route_target=…` using `useRoutedInvoices`.

Used on Purchase Management, Team Expenses, and Rule Book context pages.

## C.3 Purchase Management KPIs

KPI cards derive from routed purchase invoices (open, missing PO ref, processed %, needs review).

The three-way match register remains a **collapsible sandbox** until PO/GRN APIs exist.

## C.4 Team Expenses

| Tab | Source |
|-----|--------|
| Claims | Invoices with `route_target=Team Expenses` |
| Budgets | Employee Master (`useEmployeeMasters`) |
| Categories | Enabled team expense rules (`useRuleBookConfig`) |

Adapters: `frontend/src/lib/routePageAdapters.ts`

## C.5 Payments queue

`PaymentsPage` uses `usePayablesQueue` — processed invoices with a due date and positive total (matches dashboard `payments_queue_count`).

## C.6 Live Evaluation — disabled rules

Backend returns `email_rule_disabled` when a disabled email capture rule would have matched.

`LiveEvaluation.tsx` shows **Would match: {name}** with a dashed amber badge.

## Verify

```powershell
cd frontend
npm run build

cd ..\backend
pytest tests/test_rule_book_evaluate.py tests/test_dashboard_api.py -q
```
