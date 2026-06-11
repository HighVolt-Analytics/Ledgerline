# Azure resources → app environment variables

Quick start: [README.md](../README.md) · template: [backend/.env.example](../backend/.env.example)

Resource group: `rg-email-to-accounting-automation` (eastus2).

## Integrated services

| Azure resource | Env vars | App behavior |
|----------------|----------|--------------|
| PostgreSQL Flexible Server | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Builds `postgresql+asyncpg://…?ssl=require` for SQLAlchemy |
| Redis Cache | `REDIS_HOST`, `REDIS_SSL_PORT`, `REDIS_PASSWORD` | Builds `rediss://` broker (`/0`) and result backend (`/1`); Celery uses SSL |
| Blob Storage | `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_STORAGE_CONTAINER` | PDFs stored in Azure Blob (falls back to `UPLOAD_DIR` when unset) |
| Document Intelligence | `AZURE_DI_ENDPOINT` / `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`, `AZURE_DI_KEY` | OCR fallback when local parse is low confidence |
| Microsoft Graph | `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `GRAPH_MAILBOX` | Inbox poll + folder moves |
| Microsoft Graph OAuth | `GRAPH_OAUTH_REDIRECT_URI`, `GRAPH_OAUTH_FRONTEND_RETURN_URL` | User mailbox sign-in ([mailbox-oauth-setup.md](./mailbox-oauth-setup.md)) |
| Application Insights | `APPLICATIONINSIGHTS_CONNECTION_STRING` | OpenTelemetry on API startup (auto on App Service; set `ENABLE_APPLICATION_INSIGHTS=true` to test locally) |

Optional metadata (Integrations UI / CORS):

- `AZURE_LOCATION`, `AZURE_RESOURCE_GROUP`, `AZURE_WEBAPP_URL`

## Recommended `.env` pattern

Use **component variables** for Postgres and Redis so passwords with `@` or `=` are URL-encoded automatically:

```env
POSTGRES_HOST=pg-emailacct-49964.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DB=email_accounting
POSTGRES_USER=pgadmin
POSTGRES_PASSWORD=<secret>

REDIS_HOST=redis-emailacct-49964.redis.cache.windows.net
REDIS_SSL_PORT=6380
REDIS_PASSWORD=<secret>

APPLICATIONINSIGHTS_CONNECTION_STRING=<connection-string>
```

You can also pass a full `DATABASE_URL` export — the app rewrites `postgresql://` → `postgresql+asyncpg://` and `sslmode=require` → `ssl=require`.

## Local dev with Azure backends

1. Copy values into `backend/.env` (never commit).
2. Allow your client IP on Azure Postgres and Redis firewalls.
3. Restart API and Celery:

```powershell
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8001
# separate terminals:
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat --loglevel=info
```

Or use Docker without local Postgres/Redis:

```powershell
docker compose -f docker-compose.azure.yml up -d --build
```

## Verify integrations

```powershell
Invoke-RestMethod http://localhost:8001/api/settings | ConvertTo-Json -Depth 5
```

Expect `azure_postgres_enabled`, `azure_redis_enabled`, `blob_enabled`, `azure_di_enabled`, `graph_enabled`, and `appinsights_enabled` to be `true` when configured.

## App Service (not deployed by this repo)

Set the same variables in **Configuration → Application settings** for `app-emailacct-49964`. Deployment (GitHub Actions, zip deploy, etc.) is separate from env wiring.

## Security

- Never commit `backend/.env` (gitignored).
- Rotate Postgres, Redis, Storage, Document Intelligence, and Graph secrets if they were shared in chat or tickets.
