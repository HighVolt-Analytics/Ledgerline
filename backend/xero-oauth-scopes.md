# Xero OAuth scopes (LedgerLink)

Research note for later stages (sync, ACCPAY, attachments, webhooks).  
**Connect already works** with the string below. Do not add `.read` next to the matching write scope.

Retrieved from Xero’s current (2025–2026) granular / additive model. Official docs: [OAuth 2.0 scopes](https://developer.xero.com/documentation/guides/oauth2/scopes), [OAuth overview](https://developer.xero.com/documentation/guides/oauth2/overview), [tenants/connections](https://developer.xero.com/documentation/guides/oauth2/tenants), [Invoices](https://developer.xero.com/documentation/api/accounting/invoices), [Attachments](https://developer.xero.com/documentation/api/accounting/attachments), [Webhooks](https://developer.xero.com/documentation/guides/webhooks/overview), [Granular scopes FAQ](https://developer.xero.com/faq/oauth2/granular-scopes).

---

## What we send today (`backend/.env` → `XERO_SCOPES`)

```
openid profile email offline_access accounting.settings accounting.contacts accounting.invoices accounting.attachments
```

This matches the recommended combined string. Restart the API after any change.

---

## How scopes behave

- **Additive:** If the user connects with set A, then authorizes again with set B, the token keeps **A + B**. You cannot drop one scope from a live token; disconnect/revoke the whole connection to reduce access.
- **Write includes read:** `accounting.invoices`, `accounting.settings`, `accounting.contacts`, `accounting.attachments` allow GET as well as POST/PUT/DELETE. The `*.read` names are read-only only.
- **Do not request both:** `accounting.invoices` **and** `accounting.invoices.read` together → **`invalid_scope`**. Same for settings, contacts, attachments.
- **`accounting.transactions`:** Deprecated. Replaced by granular names (`accounting.invoices`, `accounting.payments`, `accounting.banktransactions`). New apps reject it (`invalid_scope`). We hit this on first Connect.
- **`app.connections`:** Not needed for our web-app user OAuth. `GET https://api.xero.com/connections` works with a normal user token that already has accounting scopes. `app.connections` is for machine-to-machine / client-credentials cleanup only.
- **OIDC:** `openid` is required for identity. `profile` and `email` are recommended so we can see who authorised. **`offline_access` is required** for refresh tokens (access token ~30 minutes; refresh is rolling ~60 days and rotates on each use).
- **Web vs PKCE:** Our backend stays **authorization code + client secret**. PKCE is for public/native apps. Apps created **on or after 2 March 2026** must use granular scopes only. Legacy `accounting.transactions` is aimed to be gone platform-wide by **September 2027**.

---

## Stage → scopes (when we implement later)

| Step | What we call | Scopes |
|------|----------------|--------|
| Connect + list orgs | `GET /connections` | `openid` `offline_access` (+ `profile` `email`) plus any accounting scope we already request |
| Settings sync | Org, COA, tax, currencies, tracking | `accounting.settings` (or `.read` only if we never create/edit those in Xero) |
| Contacts | GET/POST suppliers | `accounting.contacts` |
| ACCPAY draft bills | POST invoices `Type=ACCPAY` `Status=DRAFT` | `accounting.invoices` (also covers credit notes, POs, items on that API family — we still only **send** drafts) |
| PDF on the bill | Attachments on the invoice | `accounting.attachments` (Xero: upload to `/Invoices/{id}/Attachments/{name}`) |
| Inbound webhooks | HMAC on `x-xero-signature` | **No OAuth scope** to receive. Pulling the updated invoice still uses `accounting.invoices` + `offline_access`. Needs `XERO_WEBHOOK_KEY` and a public HTTPS URL. |

---

## Do not request (our product)

`payroll.*`, report scopes, `accounting.banktransactions`, journals/assets/projects unless a later product decision says so. They enlarge consent, may require Advisor/payroll admin, and hurt app-store review.

---

## If Connect fails with `invalid_scope` again

1. We asked for a name **not ticked** on the Xero app.  
2. We asked for **write + `.read`** of the same area.  
3. We asked for **`accounting.transactions`**.

Fix: align `XERO_SCOPES` with **checked** portal names, then recreate the API container so `.env` reloads.
