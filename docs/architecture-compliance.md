# Ledgerline v4 Rule Book — architecture compliance

This document tracks implementation status against the v4 Rule Book Architecture (Phases A–I).

## Completed

| Phase | Scope | Status |
|-------|--------|--------|
| **A** | Email capture gate, legacy cascade, upload routing | Done |
| **§2.1** | Eval sequence: purchase → expense → team GL cascade; PO plausibility; email metadata on invoices | Done |
| **§2.2** | `priority` on all category rules; first-match-wins; disabled-rule preview in Live Eval | Done |
| **§4 Purchase** | Full §4.3 match logic; PO ledger inheritance to invoice/GRN | Done |
| **B** | Pending vendor hold, team expense validation | Done |
| **C** | Route pages wired to live invoice API | Done |
| **D** | Rule-book audit, admin permissions, changelog | Done |
| **E** | PO/GRN models, three-way match API, Purchase UI | Done |
| **F** | Payments table + workflow API, Payments page tabs | Done |
| **G** | Expenses Management page (`/expenses`) + nav badge | Done |
| **H** | Privilege matrix enforcement + policy audit | Done |
| **I** | Ledger Link, wallet summary, billing credits, matrix conflicts | Done |

## APIs added (E–I)

- `GET /api/purchases` — list PO rows with three-way match
- `POST /api/purchases/{id}/grn` — record goods receipt
- `POST /api/purchases/{id}/approve-variance` — approve variance
- `GET /api/payments` — list payment workflow rows
- `PATCH /api/payments/{id}` — advance status (queue → awaiting → scheduled → paid)
- `GET /api/payments/wallet-summary` — aggregate balance from live payment rows
- `GET /api/ledger-link` — reconciliation overview + export register by route target
- `GET /api/billing` — org credit balance and packs
- `PATCH /api/billing` — auto-recharge settings
- `POST /api/billing/purchase` — add credits from a pack (file-backed store)
- `GET /api/matrix` — includes `conflict_with` / `conflict_detail` for duplicate rows

Purchase orders are created when invoices routed to **Purchase Management** include a `po_reference`. Payments are created when invoices reach **processed** with a due date.

## Workspace pages — wiring status

| Page | Status |
|------|--------|
| Dashboard, Inbox, Team Expenses, Expenses Management, Purchase Management | Live API |
| Approvals, Vendors, Rule Book, Vault, Reports, Integrations | Live API |
| Reconciliation | Live API |
| Document Matrix | Live API (duplicate side-by-side from API) |
| Payments | Live API (wallet from payment aggregates) |
| Ledger Link | Live API |
| Billing | Live API (org-scoped credits store) |
| Settings | Partial (app settings API; full RBAC admin UI pending) |

## Privilege matrix (H)

JWT roles map to matrix rows: `admin` → Admin, `member` → Approver. Enforced on:

- `POST /api/approvals/{id}/approve` — Approve
- `POST /api/approvals/{id}/reject` — Reject
- `DELETE /api/approvals/{id}` — Reject
- `POST /api/invoices/{id}/publish` — Publish
- `PUT /api/approval-policy` — Edit Policy
- `POST /api/approval-policy/unlock` — Edit Policy

Policy changes write `approval_policy_updated` / `approval_policy_unlocked` audit events.

## Migration

Run on Azure Postgres (or local):

```bash
cd backend
alembic upgrade head
```

Revision `012` creates `purchase_orders`, `goods_receipts`, and `payments`.

## Remaining (beyond rule-book architecture)

- Full RBAC roles (Bookkeeper, Auditor, Finance lead) in JWT / user admin UI
- Stripe live disbursement (wallet top-up/withdraw remain disabled preview)
- Live Stripe billing checkout (credit packs update org balance via API stub)
- PO master import (PO rows currently derive from invoice `po_reference`)
