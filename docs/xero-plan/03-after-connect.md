# Stage 3 — After Connect (not the current build)

Do **not** start this until Stage 2 exit criteria are met.

Still **no UI redesign**. Use existing buttons/APIs; implement behind them in `integrations/xero` + `core` (canonical + dispatch).

| Later step | What | You may need to provide |
|------------|------|-------------------------|
| Org already selected | Single-org auto-bind vs picker | How many demo orgs the user has |
| Sync settings/contacts | Pull COA, tax, tracking, contacts | Demo company with COA |
| Mapping | Existing mapping UI → new mapping store/API if old one is commented | Which GL/tax/supplier to use for a test bill |
| Export | `core` canonical from **existing invoice** → `xero` ACCPAY DRAFT + PDF | A supplier invoice in this tenant |
| Multi-adapter send | `dispatch` to several adapters | Second adapter not in v1 |
| Webhooks | HMAC to existing `/api/webhooks/xero` | Webhook key + ngrok |

`Temp.md` payload/HMAC details apply here, not at Connect.

Old export/sync modules: comment out when those routes are switched, same as Connect.
