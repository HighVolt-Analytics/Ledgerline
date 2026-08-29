# Stage 2 — Connect (new Integrations layer)

**Status: implemented.** Existing UI routes call `app.integrations.xero`. Legacy Xero token exchange is a shim to the new module.

No mapping, sync, or export in this stage.

---

## Flow

1. UI (unchanged) `GET /api/integrations/xero/connect` with admin JWT.  
2. **core** creates one-time **state** (tenant id + user + expiry).  
3. **xero** builds authorize URL (client id, redirect URI, scopes, state).  
4. Browser → Xero → user allows demo org.  
5. Xero → `GET /api/integrations/xero/callback?code&state`.  
6. **core** validates state.  
7. **xero** exchanges code at identity.xero.com, fetches `/connections`.  
8. Encrypt tokens (**core** crypto), save **per tenant**.  
9. Redirect to `http://localhost:5173/integrations?xero=connected` (or existing org-selection query if multiple orgs — only if the **current UI already** shows the picker; if select API still hits old code, implement **new** select in xero folder with **same** `POST /api/integrations/xero/connections/select` path, or Connect is incomplete for multi-org).

If multi-org appears and the old select endpoint would call legacy code: **reimplement select in the new layer** with the same URL (still no UI change).

---

## Implementer

1. Add `integrations/core` + `integrations/xero` (OAuth only).  
2. Point connect + callback (and select if needed) at new code.  
3. Comment out old connect/callback implementations.  
4. Do not import old `xero_token_service` / `accounting_integration_service` for the happy path.  
5. Restart API; test with demo company.

**Implemented:** `GET /api/integrations/xero/connect`, callback, list connections, and select org go through `app.integrations.xero`. Tokens encrypted with `core.token_crypto` (same key as before). Existing UI unchanged.

---

## Exit criteria

- [ ] Connect redirects to Xero  
- [ ] Callback succeeds (not redirect_uri mismatch / invalid_grant)  
- [ ] Integrations shows connected (or org picker via **new** select)  
- [ ] Tokens not in frontend  
- [ ] Old connect code commented, not executed  

---

## Before this step — you must provide

All of Stage 0: Client ID, secret, exact redirect URI in the portal, demo user, `.env` filled, API restarted.
