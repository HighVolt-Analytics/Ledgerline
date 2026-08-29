# Stage 0 — What you must provide (before Connect)

Nothing in the new Integrations layer can complete OAuth without this. The implementer cannot register the Xero app for you.

Hand secrets **out of git**. Put them in local `backend/.env` (combined env). Never commit `.env`.

---

## Required before Stage 2 (Connect) — blocking

### Xero Developer Portal

- [ ] **Standard Web App** (auth code + client secret). **Not** Custom Connection.
- [ ] **Client ID**
- [ ] **Client secret**
- [ ] Redirect URI **exactly**: `http://localhost:8001/api/integrations/xero/callback`
- [ ] Scopes allowed on the app (tell us the exact strings). Recommended starting set:

```
openid profile email offline_access
accounting.settings accounting.settings.read
accounting.contacts accounting.contacts.read
accounting.transactions accounting.transactions.read
```

If the portal only shows other names (`accounting.invoices`, attachments), send a screenshot; we will set `XERO_SCOPES` to match.

### Xero user

- [ ] Login that can authorize the app  
- [ ] **Demo Company** for first Connect (not a live client org)

### Runtime

- [ ] API on **8001**, UI on **5173**, logged in as tenant **admin** (Connect is admin-only; **no UI change**)

### `.env` keys (you provide values)

```
XERO_ENABLED=true
XERO_CLIENT_ID=
XERO_CLIENT_SECRET=
XERO_REDIRECT_URI=http://localhost:8001/api/integrations/xero/callback
XERO_OAUTH_FRONTEND_RETURN_URL=http://localhost:5173/integrations
```

Optional: `XERO_SCOPES=` space-separated list matching the portal.

Restart the API after editing `.env`.

---

## Not required for Connect

- Webhook signing key  
- Ngrok  
- Chart of accounts mapping  
- New extraction  
- Spreadsheet of all Xero objects  

Webhook key is only when we add inbound webhooks (after Connect).

---

## Staging later (not blocking local Connect)

Redirect: `https://staging.highvolt.tech/ledgerlink/api/integrations/xero/callback`  
Must be added on the **same** Xero app (extra URI) when you test staging.
