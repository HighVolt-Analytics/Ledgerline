# Accounting integrations (Xero & QuickBooks Online)

OAuth connect/disconnect and connection status only. **No bill, journal, or payment writes** are performed yet.

## Overview

Tenant admins connect Xero or QuickBooks Online from **Integrations**. Tokens are stored encrypted server-side (`token_vault`) and are never returned to the browser or logged.

| Provider | `provider` value | Connect API | Callback API |
|----------|------------------|-------------|--------------|
| Xero | `xero` | `GET /api/integrations/xero/connect` | `GET /api/integrations/xero/callback` |
| QuickBooks Online | `quickbooks_online` | `GET /api/integrations/quickbooks/connect` | `GET /api/integrations/quickbooks/callback` |

Additional endpoints:

- `GET /api/integrations/status` — connection status per provider (admin)
- `POST /api/integrations/{provider}/disconnect` — clear tokens and mark disconnected (admin)

Audit events: `accounting_integration_connected`, `accounting_integration_disconnected`, `accounting_integration_error`.

## Environment variables

### Shared

| Variable | Description |
|----------|-------------|
| `ACCOUNTING_OAUTH_FRONTEND_RETURN_URL` | Where OAuth callbacks redirect after success/error (Integrations page). Falls back to `XERO_OAUTH_FRONTEND_RETURN_URL`, `QUICKBOOKS_OAUTH_FRONTEND_RETURN_URL`, then `GRAPH_OAUTH_FRONTEND_RETURN_URL`. |

### Xero

| Variable | Required | Description |
|----------|----------|-------------|
| `XERO_CLIENT_ID` | Yes | Xero app client id |
| `XERO_CLIENT_SECRET` | Yes | Xero app client secret |
| `XERO_REDIRECT_URI` | Yes | Must match Xero app redirect URI exactly |
| `XERO_OAUTH_SCOPES` | No | Default: `openid profile email accounting.settings.read offline_access` |

### QuickBooks Online

| Variable | Required | Description |
|----------|----------|-------------|
| `QUICKBOOKS_CLIENT_ID` | Yes | Intuit app client id |
| `QUICKBOOKS_CLIENT_SECRET` | Yes | Intuit app client secret |
| `QUICKBOOKS_REDIRECT_URI` | Yes | Must match Intuit redirect URI exactly |
| `QUICKBOOKS_ENVIRONMENT` | No | `sandbox` (default) or `production` |
| `QUICKBOOKS_OAUTH_SCOPES` | No | Default: `com.intuit.quickbooks.accounting` |

## Redirect URLs

Register these **exact** callback URLs with each provider (adjust host/path for your deployment):

**Local development**

```
http://localhost:8001/api/integrations/xero/callback
http://localhost:8001/api/integrations/quickbooks/callback
```

**Staging example** (with path prefix)

```
https://staging.example.com/ledgerlink/api/integrations/xero/callback
https://staging.example.com/ledgerlink/api/integrations/quickbooks/callback
```

Frontend return URL (query params `?xero=` / `?quickbooks=`):

```
http://localhost:5173/integrations
```

## Sandbox setup

### Xero

1. Create a app at [Xero Developer](https://developer.xero.com/app/manage).
2. Set **OAuth 2.0 redirect URI** to `XERO_REDIRECT_URI`.
3. Enable scopes used by `XERO_OAUTH_SCOPES` (at minimum organisation connection + offline access).
4. Copy Client id and Client secret into env.
5. Use a [Xero demo company](https://developer.xero.com/documentation/guides/oauth2/auth-flow) for testing.

### QuickBooks Online

1. Create an app in the [Intuit Developer Portal](https://developer.intuit.com/).
2. Add redirect URI `QUICKBOOKS_REDIRECT_URI`.
3. Use **Development** keys with `QUICKBOOKS_ENVIRONMENT=sandbox`.
4. Connect using a [sandbox company](https://developer.intuit.com/app/developer/qbo/docs/get-started/create-a-sandbox-company).
5. The callback receives `realmId` (company id) from Intuit; Ledgerline stores it as `provider_tenant_id`.

## Security

- Tenant isolation: `accounting_integrations` table has RLS; all queries filter by `tenant_id`.
- Only tenant **admins** may connect or disconnect.
- Access and refresh tokens are encrypted at rest; API responses expose status and display name only.
- OAuth callbacks are public (provider redirect) but validated via signed JWT `state`.

## Next planned sync features

Not implemented in this foundation:

- Push approved bills / vendor invoices to Xero / QBO
- Journal entry export after ledger posting
- Chart of accounts import for mapping
- Contact / vendor sync
- Token refresh background job and `expired` status handling
- Webhook subscriptions for provider change notifications

See `backend/app/services/accounting_integration_service.py` for OAuth implementation entry points.
