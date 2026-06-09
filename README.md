# LedgerLink

Invoice-to-accounting automation: ingest emails and PDFs, validate, route via rule book, approve, and export to your ledger.

## Repository layout

```
Email_to_Acc_proj/
├── backend/          # FastAPI API, Celery workers, Alembic migrations
│   ├── app/          # Application code (api, models, services)
│   ├── alembic/      # Database migrations
│   ├── tests/        # Pytest suite
│   ├── uploads/      # Runtime file storage (gitignored; .gitkeep only)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example  # Copy to .env — never commit .env
├── frontend/         # React + TypeScript + Vite UI
│   ├── src/          # Pages, components, API client
│   └── package.json
├── docs/             # Phase notes and API reference
├── scripts/          # Local setup helpers (phase0.ps1, setup-venv.ps1)
├── docker-compose.yml          # Full local stack (Postgres + Redis in Docker)
└── docker-compose.azure.yml    # API + Celery only; Postgres/Redis on Azure
```

**Do not commit:** `backend/.env`, `backend/uploads/*`, `frontend/node_modules/`, `frontend/dist/`, caches.

## Quick start — Azure backends (recommended)

The project is wired for **Azure PostgreSQL**, **Redis**, **Blob Storage**, **Document Intelligence**, and **Microsoft Graph**. Run the API and Celery on your machine (or in Docker) and point them at Azure via `backend/.env`.

Full variable reference: **[docs/azure-env-mapping.md](docs/azure-env-mapping.md)**

### 1. Configure environment

```powershell
copy backend\.env.example backend\.env
# Fill in POSTGRES_*, REDIS_*, AZURE_* values from Azure Portal / Key Vault
```

Use **component variables** for Postgres and Redis (`POSTGRES_HOST`, `REDIS_HOST`, etc.) — the app builds `postgresql+asyncpg://` and `rediss://` URLs with SSL automatically (`backend/app/azure_env.py`).

Allow your client IP on **Azure Postgres** and **Redis** firewalls before connecting.

### 2. Migrate and run (venv)

```powershell
.\scripts\setup-venv.ps1
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
python seed.py
```

**Terminal 1 — API:**

```powershell
cd backend
uvicorn app.main:app --reload --port 8001
```

**Terminal 2 — Celery worker:**

```powershell
cd backend
celery -A app.workers.celery_app worker --loglevel=info
```

**Terminal 3 — Celery beat** (email poll):

```powershell
cd backend
celery -A app.workers.celery_app beat --loglevel=info
```

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev
```

| URL | Purpose |
|-----|---------|
| http://localhost:5173 | Ledgerline UI (proxies `/api` → 8001) |
| http://localhost:8001/health | Health check |
| http://localhost:8001/docs | Swagger UI |
| http://localhost:8001/api/settings | Integration flags (`azure_postgres_enabled`, `blob_enabled`, etc.) |

### Docker with Azure backends

Runs API, worker, and beat in containers — **no local Postgres/Redis**:

```powershell
docker compose -f docker-compose.azure.yml up -d --build
docker compose -f docker-compose.azure.yml exec api alembic upgrade head
```

`backend/.env` is loaded via `env_file` in `docker-compose.azure.yml`.

---

## Alternative — fully local (Docker)

For offline dev with Postgres and Redis in Docker (no Azure):

```powershell
cd Email_to_Acc_proj
.\scripts\phase0.ps1
```

Or step by step:

```powershell
docker compose up -d postgres redis mailhog api worker beat
docker compose exec api alembic upgrade head
docker compose exec api python seed.py
docker compose exec api pytest -v
```

| Container | Port | Role |
|-----------|------|------|
| api | 8001 | FastAPI |
| worker | — | Celery worker |
| beat | — | Inbox poll (`GRAPH_POLL_INTERVAL_MINUTES`, default 2) |
| postgres | 5432 | Database |
| redis | 6379 | Celery broker |
| mailhog | 8025 | Dev SMTP UI |

Local venv against Docker DB only:

```powershell
.\scripts\setup-venv.ps1
docker compose up -d postgres redis mailhog
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
uvicorn app.main:app --reload --port 8001
```

---

## API envelope

Every response:

```json
{
  "data": {},
  "error": null,
  "meta": { "page": 1, "total": 0, "pages": 0 }
}
```

Requests accept `X-Correlation-ID` for tracing.

## Environment variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | **Azure Postgres** (preferred) — app builds `DATABASE_URL` |
| `REDIS_HOST`, `REDIS_SSL_PORT`, `REDIS_PASSWORD` | **Azure Redis** (preferred) — app builds Celery broker URLs |
| `DATABASE_URL` | Full Postgres URL (local Docker or Azure export) |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis URLs (local) |
| `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_STORAGE_CONTAINER` | Blob PDF storage |
| `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` | Document Intelligence (parse fallback) |
| `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `GRAPH_MAILBOX` | Microsoft Graph email ingest |
| `UPLOAD_DIR` | Local PDF fallback when Blob unset |
| `RULE_BOOK_CONFIG_PATH` | Org rule book JSON template |
| `CHART_OF_ACCOUNTS_PATH` | Expense category → GL code |
| `AUTH_REQUIRED`, `JWT_SECRET` | Dashboard login |
| `CORS_ORIGINS` | Comma-separated origins |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights (optional locally) |

| Run mode | Where config lives |
|----------|-------------------|
| **Azure-backed venv** (recommended) | `backend/.env` |
| Docker + Azure | `backend/.env` via `docker-compose.azure.yml` |
| Docker local stack | `docker-compose.yml` `environment` block |
| App Service | Azure Portal → Configuration → Application settings |

See [docs/azure-env-mapping.md](docs/azure-env-mapping.md) for the complete Azure mapping.

## Tests

```powershell
cd backend
pytest -v
```

## Feature phases (pipeline)

| Phase | Topic | Doc |
|-------|--------|-----|
| 1 | Microsoft Graph email ingest | [docs/phase1-graph.md](docs/phase1-graph.md) |
| 1b | PDF parsing (local + Azure DI) | [docs/phase1b-parsing.md](docs/phase1b-parsing.md) |
| 2 | Blob storage + vendor registry | [docs/phase2-blob-storage.md](docs/phase2-blob-storage.md) |
| 5 | Excel workbook export | [docs/phase5-workbook-export.md](docs/phase5-workbook-export.md) |
| 6 | Graph folder moves (Processed / Exceptions) | [docs/phase6-graph-folders.md](docs/phase6-graph-folders.md) |
| 7 | Rule book backend evaluator | [docs/phase7-rule-book.md](docs/phase7-rule-book.md) |

Trigger email ingest after Graph is configured:

```powershell
Invoke-RestMethod -Method POST http://localhost:8001/api/process/trigger
```

Graph folder moves (requires `Mail.ReadWrite`):

```env
GRAPH_FOLDER_MOVES_ENABLED=true
GRAPH_PROCESSED_FOLDER=Processed
GRAPH_EXCEPTIONS_FOLDER=Exceptions
```

## Rule book architecture (Phases A–D)

| Phase | Focus | Doc |
|-------|--------|-----|
| A | Email capture gate, legacy cascade, upload routing | [docs/phase-a-rule-book.md](docs/phase-a-rule-book.md) |
| B | Pending vendor hold, employee validation, team policy | [docs/phase-b-rule-book.md](docs/phase-b-rule-book.md) |
| C | UI wired to API (routed docs, payables, auto-remap) | [docs/phase-c-rule-book.md](docs/phase-c-rule-book.md) |
| D | Rule-change audit + admin permissions | [docs/phase-d-rule-book.md](docs/phase-d-rule-book.md) |

## Assessment brief alignment

See [docs/brief-compliance.md](docs/brief-compliance.md) for validation rules (VR01–VR08), line items, PO/cost centre, and multi-format attachments.

## Frontend

React UI wired to `/api/*`. See [frontend/README.md](frontend/README.md) and [docs/frontend-api.md](docs/frontend-api.md).

Main routes: Dashboard, Inbox, Approvals, Rule Book, Purchase Management, Team Expenses, Payments, Vault, Matrix, Reports.
