# Stage 1 — Architecture (new layer)

**Status: implemented** (packages under `backend/app/integrations/`). HTTP Connect still uses the **legacy** routes so the working Xero login is unchanged until Stage 2.

Replace the old “sources of truth / extend existing services” plan.

---

## Folders (on disk)

| Path | Owns |
|------|------|
| `app/integrations/core/oauth_state.py` | JWT CSRF state + Redis jti |
| `app/integrations/core/token_crypto.py` | Encrypt/decrypt tokens |
| `app/integrations/core/canonical.py` | Stub — invoice snapshot later |
| `app/integrations/core/dispatch.py` | Stub — `send(..., adapters=["xero"])` later |
| `app/integrations/xero/oauth.py` | Authorize/token/connections URLs + scopes |
| `app/integrations/xero/client.py` | `Authorization` + `xero-tenant-id` headers |
| `app/integrations/xero/connect_api.py` | `build_connect_url` — **not** mounted on FastAPI yet |

Old tree (`app/services/integration/xero/`, old accounting_integrations handlers) is **legacy**. New code must not import it. At Stage 2 cutover, comment out old route bodies and point routes at `integrations.xero`.

---

## Canonical fields (decision A)

- Source = **current** invoice, line items, vendor, tax, currency, PDF location.  
- `core/canonical.py` (when we export) builds **our** dict.  
- `xero/` maps **subset** to ACCPAY (and later other adapters map their subset).  
- Union of fields grows only when a new destination needs something we do not store yet — then we discuss extraction. **Not now.**

---

## Multi-adapter (decision 7)

`core/dispatch.py` (can be stub): `send(canonical, adapters=["xero", ...])`.  
v1: only `"xero"` is implemented. Do not build other vendor folders yet.

---

## HTTP (no UI change)

Keep existing frontend calls, including:

- `GET /api/integrations/xero/connect` → `{ connect_url }`  
- `GET /api/integrations/xero/callback`  
- Return URL: Integrations with `?xero=connected` (and org-select query if the old UI already handles it)

New handlers, same contracts.

---

## Persistence

Store connection **per LedgerLink tenant** (encrypted access + refresh, xero org id once selected). Reuse existing tables **only if** they fit without pulling old services. If a table is tightly coupled to old code, add a **new** connection table owned by the new layer — prefer reuse of `xero_connections` / token vault **schema** if it is just columns, not old Python.

---

## `Temp.md` / spreadsheet

Use for: OAuth grant type, token lifetimes, REST headers (`Authorization`, `xero-tenant-id`), HMAC webhooks later, ACCPAY vs ACCREC.  
Do **not** use for: folder names, webhook path copy-paste if it disagrees with our existing public path (when we add webhooks, keep `POST /api/webhooks/xero` unless we version a new path and never change the UI — UI has no webhook).  
Do **not** use spreadsheet as a backlog of objects to build for Connect.
