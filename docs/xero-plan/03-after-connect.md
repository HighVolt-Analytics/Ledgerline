# Stage 3 — After Connect (sync, mapping, export)

**Status: implemented** (webhooks not in this stage).

Still **no UI redesign**. Existing Integrations buttons/APIs now run through `app/integrations/xero` + `core` (canonical + dispatch).

| Step | What | You may need to provide |
|------|------|-------------------------|
| Org already selected | Stage 2 Connect | Demo org already connected |
| Sync settings/contacts | Pull org, COA, tax, tracking, contacts | Demo company with a chart of accounts |
| Mapping | Existing mapping UI / APIs | Which GL / tax / supplier to use for a test bill |
| Export | Canonical from existing invoice → ACCPAY DRAFT + PDF | A processed supplier invoice in this tenant |
| Multi-adapter send | `dispatch` to several adapters | Not in v1 (Xero only) |
| Webhooks | HMAC to existing `/api/webhooks/xero` | **Not this stage** — needs webhook key + ngrok later |

---

## Implemented

- `POST /api/integrations/xero/sync/settings` and `.../sync/contacts` → `integrations/xero/sync.py` (new HTTP client + token refresh).
- Canonical snapshot: `integrations/core/canonical.py` (existing invoice/lines/PDF, no new extraction).
- ACCPAY DRAFT mapper: `integrations/xero/accpay.py`.
- Export + PDF attach: `integrations/xero/export.py` via `POST /api/integrations/xero/invoices/{id}/push`.
- `integrations/core/dispatch.py` sends v1 to Xero only.
- Webhooks left on the old handler until you have `XERO_WEBHOOK_KEY` and a public URL.

**Next (not this file):** create contacts/GL **in Xero** when LedgerLink creates them — [Xero-write-backend.md](../../Xero-write-backend.md).


---

## Exit criteria

- [ ] Sync settings completes without a 401/403 from Xero
- [ ] Sync contacts shows contacts in the existing UI
- [ ] Mapping still uses the existing screens
- [ ] Push a processed supplier invoice → Draft bill in Xero demo + PDF attached when a PDF exists
- [ ] No webhook setup required for this stage
