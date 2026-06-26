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
│   ├── Dockerfile    # Production image (nginx, /ledgerlink base path)
│   └── package.json
├── k8s/              # AKS manifests (namespace: quantum-ledgerlink)
│   └── ledgerlink-config.example.yaml  # ConfigMap template incl. BASE_PATH
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
| api | 8001 → 8000 | FastAPI (host 8001 maps to container 8000) |
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
| `BASE_PATH` / `ROOT_PATH` | Reverse-proxy prefix for AKS/Front Door (e.g. `/ledgerlink`; empty locally) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights (optional locally) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_CONNECT_CLIENT_ID` | Stripe Connect (secrets — see [docs/stripe-payments.md](docs/stripe-payments.md)) |
| `STRIPE_MODE`, `STRIPE_RETURN_URL`, `STRIPE_REFRESH_URL` | Stripe Connect (non-secret URLs / mode) |

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

---

## AKS staging deployment (Quantum LedgerLink)

Staging URL: **https://staging.highvolt.tech/ledgerlink**

Manifests live in `k8s/`. Images are built and pushed to ACR by `.github/workflows/ledgerlink-staging-deploy.yml` on pushes to **`develop`** (or manual `workflow_dispatch`). The workflow targets the GitHub environment **`ledgerlink-staging`**.

### Architecture

Traffic enters through **Azure Front Door**, which routes path prefixes to AKS **LoadBalancer** origins. The cluster does **not** use NGINX Ingress.

```
Azure Front Door (staging.highvolt.tech/ledgerlink)
        │
        ├── /ledgerlink/api/*  ──►  ledgerlink-backend-public  (LoadBalancer :8001)
        │                                    │
        │                                    └── ledgerlink-api pods
        │
        └── /ledgerlink/*      ──►  ledgerlink-frontend-public (LoadBalancer :80)
                                             │
                                             └── ledgerlink-frontend pods (nginx SPA)
```

| Layer | Resource | Port |
|-------|----------|------|
| Public API origin | `ledgerlink-backend-public` (LoadBalancer) | 8001 |
| Public frontend origin | `ledgerlink-frontend-public` (LoadBalancer) | 80 |
| In-cluster API | `ledgerlink-api` (ClusterIP) | 8001 |
| In-cluster frontend | `ledgerlink-frontend` (ClusterIP) | 80 |

**Ports:** The API container listens on **8001** in AKS (`uvicorn --port 8001`). Local docker-compose maps host **8001** to container **8000**; venv dev also uses **8001**.

### Reverse-proxy path prefix (`BASE_PATH`)

Azure Front Door forwards the **full public path** to the backend LoadBalancer (e.g. `/ledgerlink/api/settings`). FastAPI routes remain at `/api/*` and `/health` on the app.

Set **`BASE_PATH=/ledgerlink`** in the `ledgerlink-config` ConfigMap (or `ROOT_PATH`). The API then:

1. Initializes FastAPI with `root_path="/ledgerlink"` so OpenAPI/Swagger URLs resolve under the public prefix.
2. Strips `/ledgerlink` from incoming request paths before routing, so `/ledgerlink/api/settings` matches the existing `/api/settings` handler.

| Request (via Front Door) | Routed internally as |
|--------------------------|----------------------|
| `/ledgerlink/api/settings` | `/api/settings` |
| `/ledgerlink/health` | `/health` |
| `/ledgerlink/docs` | `/docs` (Swagger UI) |
| `/ledgerlink/openapi.json` | `/openapi.json` |

Pod probes and direct in-cluster calls without the prefix (e.g. `GET /health`) continue to work. Leave `BASE_PATH` unset for local dev.

Example: `k8s/ledgerlink-config.example.yaml`

### Required Azure resources

| Resource | Purpose |
|----------|---------|
| **AKS cluster** | Runs `quantum-ledgerlink` namespace workloads |
| **ACR** `highvoltacr1778087855.azurecr.io` | Container images `ledgerlink-api`, `ledgerlink-frontend` |
| **Azure Front Door** | Public HTTPS entry; routes `/ledgerlink` and `/ledgerlink/api` to LoadBalancer origins |
| **Azure PostgreSQL** | Application database |
| **Azure Redis** | Celery broker and result backend |
| **Azure Blob Storage** | PDF storage (recommended in staging) |
| **Document Intelligence** | OCR fallback (optional) |
| **Microsoft Graph** (Entra app) | Email ingest |
| **Application Insights** | Telemetry (optional) |

Allow the AKS subnet (or node outbound IPs) on Postgres and Redis firewalls. Register LoadBalancer external IPs as Front Door origins after each deploy.

### Required Kubernetes secrets and config

Create in namespace **`quantum-ledgerlink`** before the first deploy:

**`acr-auth`** (image pull secret) — credentials for `highvoltacr1778087855.azurecr.io`. Referenced by all LedgerLink Deployments via `imagePullSecrets`.

**`app-secrets`** (Secret) — sensitive values only. Do not commit. Typical keys (see `backend/.env.example`):

- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `JWT_SECRET`
- `AZURE_CLIENT_SECRET`
- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_DI_KEY`
- `APPLICATIONINSIGHTS_CONNECTION_STRING` (if used)
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_CONNECT_CLIENT_ID` (see [docs/stripe-payments.md](docs/stripe-payments.md))

**`ledgerlink-config`** (ConfigMap) — non-secret app configuration:

- **`BASE_PATH=/ledgerlink`** — required for AKS/Front Door API routing (see above)
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`
- `REDIS_HOST`, `REDIS_SSL_PORT`
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `GRAPH_MAILBOX`
- `AZURE_STORAGE_CONTAINER`, `AZURE_DI_ENDPOINT`
- `UPLOAD_DIR` (e.g. `/app/uploads`)
- `RULE_BOOK_CONFIG_PATH`, `CHART_OF_ACCOUNTS_PATH`
- `CORS_ORIGINS` (include `https://staging.highvolt.tech`)
- `STRIPE_MODE`, `STRIPE_RETURN_URL`, `STRIPE_REFRESH_URL` (Payments sandbox — [docs/stripe-payments.md](docs/stripe-payments.md))
- `LOG_LEVEL`, `AUTH_REQUIRED`, `GRAPH_FOLDER_MOVES_ENABLED`, etc.

All backend Deployments (`ledgerlink-api`, `ledgerlink-worker`, `ledgerlink-beat`) mount both via `envFrom`:

```yaml
envFrom:
  - secretRef:
      name: app-secrets
  - configMapRef:
      name: ledgerlink-config
```

### GitHub Actions secrets

Configure in the **`ledgerlink-staging`** environment (or repository secrets):

| Secret | Description |
|--------|-------------|
| `AZURE_CREDENTIALS` | Service principal JSON for `azure/login` |
| `AKS_RESOURCE_GROUP` | Resource group containing the AKS cluster |
| `AKS_CLUSTER_NAME` | AKS cluster name |

### Deploy manually

```powershell
# Build and push (replace TAG with git SHA or version)
az acr login --name highvoltacr1778087855
docker build -t highvoltacr1778087855.azurecr.io/ledgerlink-api:TAG ./backend
docker build --build-arg VITE_BASE_PATH=/ledgerlink/ --build-arg VITE_API_BASE=/ledgerlink `
  -t highvoltacr1778087855.azurecr.io/ledgerlink-frontend:TAG ./frontend
docker push highvoltacr1778087855.azurecr.io/ledgerlink-api:TAG
docker push highvoltacr1778087855.azurecr.io/ledgerlink-frontend:TAG

# Apply manifests and set images
kubectl apply -f k8s/ledgerlink-api-deployment.yaml -n quantum-ledgerlink
kubectl apply -f k8s/ledgerlink-worker-deployment.yaml -n quantum-ledgerlink
kubectl apply -f k8s/ledgerlink-beat-deployment.yaml -n quantum-ledgerlink
kubectl apply -f k8s/ledgerlink-frontend-deployment.yaml -n quantum-ledgerlink
kubectl apply -f k8s/ledgerlink-services.yaml -n quantum-ledgerlink
kubectl apply -f k8s/ledgerlink-loadbalancers.yaml -n quantum-ledgerlink
kubectl set image deployment/ledgerlink-api ledgerlink-api=highvoltacr1778087855.azurecr.io/ledgerlink-api:TAG -n quantum-ledgerlink
kubectl set image deployment/ledgerlink-worker ledgerlink-worker=highvoltacr1778087855.azurecr.io/ledgerlink-api:TAG -n quantum-ledgerlink
kubectl set image deployment/ledgerlink-beat ledgerlink-beat=highvoltacr1778087855.azurecr.io/ledgerlink-api:TAG -n quantum-ledgerlink
kubectl set image deployment/ledgerlink-frontend ledgerlink-frontend=highvoltacr1778087855.azurecr.io/ledgerlink-frontend:TAG -n quantum-ledgerlink
kubectl rollout status deployment/ledgerlink-frontend -n quantum-ledgerlink
```

### Retrieve LoadBalancer external IPs

After apply, Azure provisions public IPs for the LoadBalancer services (may take 1–2 minutes):

```powershell
# All public services in the namespace
kubectl get svc -n quantum-ledgerlink -l exposure=public

# Backend origin IP (register in Azure Front Door for /ledgerlink/api/*)
kubectl get svc ledgerlink-backend-public -n quantum-ledgerlink -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'

# Frontend origin IP (register in Azure Front Door for /ledgerlink/*)
kubectl get svc ledgerlink-frontend-public -n quantum-ledgerlink -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'

# Watch until EXTERNAL-IP moves from <pending> to an address
kubectl get svc ledgerlink-backend-public ledgerlink-frontend-public -n quantum-ledgerlink -w
```

Use these IPs as Front Door origin hostnames (or point Front Door origin groups at the LoadBalancer FQDN if configured).

### Health validation

```powershell
# API health via in-cluster Service (API image has no wget/curl)
kubectl run ledgerlink-health-check \
  -n quantum-ledgerlink \
  --rm -i \
  --restart=Never \
  --image=curlimages/curl \
  -- curl -f http://ledgerlink-api.quantum-ledgerlink.svc.cluster.local:8001/health

# LoadBalancer origins (replace with IPs from kubectl get svc above)
$BACKEND_IP = kubectl get svc ledgerlink-backend-public -n quantum-ledgerlink -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
$FRONTEND_IP = kubectl get svc ledgerlink-frontend-public -n quantum-ledgerlink -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
curl -I "http://${BACKEND_IP}:8001/health"
curl -I "http://${FRONTEND_IP}/ledgerlink/"

# Public URL via Azure Front Door
curl -I https://staging.highvolt.tech/ledgerlink/
curl https://staging.highvolt.tech/ledgerlink/api/settings
curl https://staging.highvolt.tech/ledgerlink/docs

# Rollout status
kubectl get pods -n quantum-ledgerlink
kubectl rollout status deployment/ledgerlink-api -n quantum-ledgerlink
kubectl rollout status deployment/ledgerlink-worker -n quantum-ledgerlink
kubectl rollout status deployment/ledgerlink-beat -n quantum-ledgerlink
kubectl rollout status deployment/ledgerlink-frontend -n quantum-ledgerlink
```
