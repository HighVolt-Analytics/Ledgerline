# Ledgerline Frontend

React UI wired to the FastAPI backend. Dashboard, inbox, approvals, rule book, purchase/team/payments routes, vault, matrix, and reports use live `/api/*` data.

## Stack

- React 18 + TypeScript
- Vite
- React Router + TanStack Query
- Lucide icons
- Recharts (dashboard)
- Styles: `src/styles/ledgerline.css` (Tailwind + shadcn tokens)

## Run

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

**Requires backend** on http://localhost:8001. See the root [README.md](../README.md) for Azure-backed setup. Typical flow:

```powershell
# From repo root — API (terminal 1)
cd backend
uvicorn app.main:app --reload --port 8001

# Worker + beat in separate terminals (email poll + pipeline)
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat --loglevel=info
```

**Docker alternative** (Azure Postgres/Redis in `backend/.env`):

```powershell
docker compose -f docker-compose.azure.yml up -d --build
```

**Fully local alternative** (Postgres + Redis in Docker):

```powershell
docker compose up -d postgres redis mailhog api worker beat
```

API calls are proxied to port 8001 (see `vite.config.ts`).

## Pages

| Route | Screen |
|-------|--------|
| `/` | Dashboard (overview, badges, activity) |
| `/upload` | Upload + mailbox capture |
| `/approvals` | Approval queue |
| `/vendors` | Vendor registry |
| `/rules` | Rule book editor |
| `/purchases` | Purchase management (routed invoices) |
| `/team-expenses` | Team expense claims |
| `/payments` | Payables queue |
| `/vault` | Document vault |
| `/matrix` | Document matrix |
| `/reconciliation` | Daily reconciliation |
| `/integrations` | Integration status |
| `/reports` | Analytics + Excel download |
| `/settings` | App settings |
| `/invoices/:id` | Invoice detail + PDF |

## Build

```powershell
npm run build
```

Output: `frontend/dist/`

API reference: [docs/frontend-api.md](../docs/frontend-api.md)
