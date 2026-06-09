# Ledgerline Frontend

React UI aligned with **Ledgerline v2** (`Downloads/Ledgerline v2`) — same CSS bundle, shell layout (248px sidebar, search bar, Sandbox badge, theme toggle, user menu), KPI cards with sparklines, kanban approvals, and page structure. Wired to the FastAPI backend.

## Stack

- React 18 + TypeScript
- Vite
- React Router
- Lucide icons
- Recharts (dashboard)
- Styles: copied from `Ledgerline v2` build (`src/styles/ledgerline.css` — Tailwind + shadcn tokens)

## Run

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

**Requires backend** on http://localhost:8001:

```powershell
cd ..
docker compose up -d api worker postgres redis
```

API calls are proxied to port 8001 (see `vite.config.ts`).

## Pages

| Route | Screen |
|-------|--------|
| `/` | Dashboard |
| `/inbox` | Inbox + upload |
| `/approvals` | Approval queue |
| `/vendors` | Vendor registry |
| `/rules` | Rule book editor |
| `/reconciliation` | Daily RC |
| `/integrations` | Integration status |
| `/reports` | Excel download |
| `/settings` | App settings |
| `/invoices/:id` | Invoice detail + PDF |

## Build

```powershell
npm run build
```

Output: `frontend/dist/`
