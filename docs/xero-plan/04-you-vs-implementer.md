# You vs implementer

| Step | You | Implementer |
|------|-----|-------------|
| Before Connect | Xero web app, Client ID/secret, redirect URI, scopes, demo login, `.env`, API/UI running, admin user | New `core` + `xero` OAuth, wire existing routes, comment old handlers |
| After Connect works | Confirm Integrations shows connected | Stop until you ask for sync/export |
| Before first export (later) | Test invoice in app; which Xero account/tax to map | Canonical from existing DB; Xero ACCPAY mapper |
| Before webhooks (later) | Signing key, public HTTPS URL | HMAC handler in new layer |

---

## Before **implementation of Connect** you must provide

See [00-you-must-provide.md](00-you-must-provide.md). Short list:

1. Standard Web App (not Custom Connection)  
2. Client ID and Client secret  
3. Portal redirect URI = `http://localhost:8001/api/integrations/xero/callback`  
4. Scopes granted (or screenshot)  
5. Demo company user  
6. Values in `backend/.env` and API restarted  

Without that, Connect cannot succeed regardless of folder structure.
