# Accounting integrations (Xero & QuickBooks Online)

OAuth connect, organisation selection, token refresh, manual sync, invoice push, and webhooks (Xero production integration).

## Overview

Tenant admins connect Xero or QuickBooks Online from **Integrations**. Tokens are stored encrypted server-side (`token_vault`) and are never returned to the browser or logged.

| Provider | `provider` value | Connect API | Callback API |
|----------|------------------|-------------|--------------|
| Xero | `xero` | `GET /api/integrations/xero/connect` | `GET /api/integrations/xero/callback` |
| QuickBooks Online | `quickbooks_online` | `GET /api/integrations/quickbooks/connect` | `GET /api/integrations/quickbooks/callback` |

### Xero endpoints (admin JWT unless noted)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/integrations/status` | Connection status per provider |
| GET | `/api/integrations/xero/readiness` | Enabled, configured, org selected, token expiry |
| GET | `/api/integrations/xero/connections` | List Xero organisations after OAuth |
| POST | `/api/integrations/xero/connections/select` | Select organisation (`xero_connection_id` only) |
| POST | `/api/integrations/xero/sync/settings` | Sync org, accounts, tax rates, currencies |
| POST | `/api/integrations/xero/sync/contacts` | Sync contacts (ContactID keyed) |
| POST | `/api/integrations/xero/invoices/{id}/push` | Push processed invoice (ACCPAY / ACCREC) |
| GET | `/api/integrations/xero/invoices/{id}/status` | External reference / push status |
| POST | `/api/integrations/xero/disconnect` | Revoke connection + clear local state |
| POST | `/api/webhooks/xero` | Public — HMAC signature verified |

Audit events include `xero_connect_completed`, `xero_organisation_selected`, `xero_token_refreshed`, `xero_settings_sync_completed`, `xero_invoice_push_completed`, `xero_webhook_received`, and related failure events.

## Environment variables

### Shared

| Variable | Description |
|----------|-------------|
| `ACCOUNTING_OAUTH_FRONTEND_RETURN_URL` | OAuth return URL (Integrations page). |

### Xero

| Variable | Required | Description |
|----------|----------|-------------|
| `XERO_ENABLED` | No | `true` (default) / `false` kill switch |
| `XERO_CLIENT_ID` | Yes | Xero app client id |
| `XERO_CLIENT_SECRET` | Yes | Xero app client secret |
| `XERO_REDIRECT_URI` | Yes | Must match Xero app redirect URI exactly |
| `XERO_SCOPES` or `XERO_OAUTH_SCOPES` | No | Granular scopes (see below) |
| `XERO_WEBHOOK_KEY` | For webhooks | HMAC key from Xero developer portal |
| `XERO_API_BASE_URL` | No | Default `https://api.xero.com/api.xro/2.0` |
| `XERO_IDENTITY_BASE_URL` | No | Default `https://identity.xero.com` |
| `XERO_TOKEN_ENCRYPTION_KEY` | No | Optional Fernet key material override |

**Recommended scopes** (configure to match your Xero app grants):

```
openid profile email offline_access
accounting.settings accounting.settings.read
accounting.contacts accounting.contacts.read
accounting.transactions accounting.transactions.read
```

### QuickBooks Online

Unchanged — see Intuit developer portal.

## Redirect URLs (canonical)

Register these **exact** callback URLs:

**Local**

```
http://localhost:8001/api/integrations/xero/callback
```

**Staging**

```
https://staging.highvolt.tech/ledgerlink/api/integrations/xero/callback
```

**Production**

```
https://ledgerlink.highvolt.tech/api/integrations/xero/callback
```

Frontend return: `ACCOUNTING_OAUTH_FRONTEND_RETURN_URL` (e.g. `/integrations`).  
OAuth success query: `?xero=connected`. Multi-org: `?xero=organisation_selection_required`.

## Security

- Tenant RLS on `accounting_integrations`, `xero_connections`, `external_accounting_refs`.
- OAuth state: signed JWT with `jti` replay guard (Redis).
- Token refresh with Redis lock; rotated refresh tokens stored atomically.
- Webhooks: `x-xero-signature` HMAC-SHA256; tenant resolved via `xero_connections`, never from payload alone.

## Implementation

- OAuth: `backend/app/services/integration/accounting_integration_service.py`
- API client: `backend/app/services/integration/xero_client.py`
- Sync: `backend/app/services/integration/xero_sync_service.py`
- Push: `backend/app/services/integration/xero_push_service.py`
- Webhooks: `backend/app/api/xero_webhooks.py`

Migration: `063_xero_production_integration.py`
