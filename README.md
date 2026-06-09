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
├── docker-compose.yml
└── docker-compose.azure.yml
```

**Do not commit:** `backend/.env`, `backend/uploads/*`, `frontend/node_modules/`, `frontend/dist/`, caches.

## Phase 0 — Quick start

**Requires:** Docker Desktop running.

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

| URL | Purpose |
|-----|---------|
| http://localhost:8001/health | Health check |
| http://localhost:8001/docs | Swagger UI |
| http://localhost:8001/api/invoices | Invoice list |
| http://localhost:8001/api/dashboard/stats | Dashboard |
| http://localhost:8025 | Mailhog |

## Local venv (optional)

```powershell
.\scripts\setup-venv.ps1
docker compose up -d postgres redis mailhog
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
python seed.py
uvicorn app.main:app --reload --port 8000
pytest -v
```

Copy `backend/.env.example` → `backend/.env` (used by venv only; Docker uses `docker-compose.yml`).

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
| `DATABASE_URL` | `postgresql+asyncpg://...` |
| `CELERY_BROKER_URL` | Redis URL for Celery |
| `CELERY_RESULT_BACKEND` | Redis result backend |
| `UPLOAD_DIR` | PDF storage path |
| `RULE_BOOK_PATH` | Vendor/PO/keyword → expense category (`rule_book.json`) |
| `CHART_OF_ACCOUNTS_PATH` | Expense category → GL code (`chart_of_accounts.json`) |
| `CORS_ORIGINS` | Comma-separated origins |
| `LOG_LEVEL` | `INFO`, `DEBUG`, etc. |
| `SMTP_HOST` / `SMTP_PORT` | Notification SMTP |

| Run mode | Where config lives |
|----------|-------------------|
| Docker `api` / `worker` / `beat` | `docker-compose.yml` `environment` block |
| Local venv | `backend/.env` (from `.env.example`) |
| Azure (later) | `backend/.env` or Key Vault references |

## Services

| Container | Port | Role |
|-----------|------|------|
| api | 8001 | FastAPI (host port; 8000 used by another app on your machine) |
| worker | — | Celery worker |
| beat | — | Poll inbox (default every 2 min, `GRAPH_POLL_INTERVAL_MINUTES`) |
| postgres | 5432 | Database |
| redis | 6379 | Celery broker |
| mailhog | 8025 | Dev SMTP UI |

## Tests

```bash
cd backend && pytest -v
```

## Phase 1 — Graph email (see [docs/phase1-graph.md](docs/phase1-graph.md))

Set `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `GRAPH_MAILBOX` in `backend/.env`, then:

```powershell
docker compose build api worker beat
docker compose up -d
Invoke-RestMethod -Method POST http://localhost:8001/api/process/trigger
```

## Phase 1b — PDF parsing (see [docs/phase1b-parsing.md](docs/phase1b-parsing.md))

Local `pdfplumber` / PyMuPDF + regex first; optional **Azure Document Intelligence** (`prebuilt-invoice`) when text is thin or fields are incomplete.

```env
AZURE_DI_ENDPOINT=https://<resource>.cognitiveservices.azure.com/
AZURE_DI_KEY=<key>
```

Or use names from your Azure deploy export: `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` / `AZURE_DOCUMENT_INTELLIGENCE_KEY` (see [docs/azure-env-mapping.md](docs/azure-env-mapping.md)).

Restart worker after changing `.env`, then upload a PDF or trigger processing.

## Phase 5 — Excel workbook (see [docs/phase5-workbook-export.md](docs/phase5-workbook-export.md))

Multi-sheet `output_workbook` export after processing; download via `/api/reports/download`.

## Phase 2 — Blob storage (see [docs/phase2-blob-storage.md](docs/phase2-blob-storage.md))

Optional Azure Blob for PDFs; vendor registry for email routing and approved ABN (VR05).

```env
AZURE_STORAGE_CONNECTION_STRING=<from Azure portal>
AZURE_STORAGE_CONTAINER=invoices
```

Run migration and seed vendors:

```powershell
docker compose exec api alembic upgrade head
docker compose exec api python -c "import asyncio; from seed import seed_vendors_only; asyncio.run(seed_vendors_only())"
```

## Phase 6 — Graph folders (see [docs/phase6-graph-folders.md](docs/phase6-graph-folders.md))

Moves each processed email to **Processed** or **Exceptions** under Inbox. Requires `Mail.ReadWrite` and migration `004`.

```env
GRAPH_FOLDER_MOVES_ENABLED=true
GRAPH_PROCESSED_FOLDER=Processed
GRAPH_EXCEPTIONS_FOLDER=Exceptions
```

## Assessment brief alignment

See [docs/brief-compliance.md](docs/brief-compliance.md) for validation rules (VR01–VR08), line items, PO/cost centre, and multi-format attachments.

## Frontend (Ledgerline UI)

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 (proxies `/api` → http://localhost:8001). Design matches `Ledgerline v2` mock; see [frontend/README.md](frontend/README.md).

API reference: [docs/frontend-api.md](docs/frontend-api.md)

## Roadmap

- **Phase 1b:** PDF parsing (local + Azure DI fallback)
- **Phase 2:** Blob storage + vendor approval — see [docs/phase2-blob-storage.md](docs/phase2-blob-storage.md)
- **Phase 3–7:** Full pipeline hardening
- **Phase 8:** React frontend (wire to `/api/*` per frontend-api doc)
