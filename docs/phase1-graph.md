# Phase 1 — Microsoft Graph email ingestion

Poll a Microsoft 365 mailbox for unread emails with PDF attachments. No Azure resource group required — only an **Entra ID app registration**.

## Azure setup (you do this)

1. **Entra ID** → **App registrations** → **New registration**
2. Note **Tenant ID**, **Client ID**
3. **Certificates & secrets** → new client secret
4. **API permissions** → Microsoft Graph → **Application** permissions (not Delegated):
   - `Mail.Read` — list and download mail
   - `Mail.ReadWrite` — **required** to mark messages read and move to folders (Phase 6)
5. **Grant admin consent** for your tenant (green checkmarks)
6. Use a mailbox UPN, e.g. `invoices@yourcompany.com`

## Configure app

Copy into `backend/.env`:

```env
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-secret
GRAPH_MAILBOX=invoices@yourcompany.com
GRAPH_MAX_MESSAGES=50
GRAPH_POLL_INTERVAL_MINUTES=2
```

**Poll interval:** Celery Beat runs automatically (no manual trigger needed). Default is **2 minutes** — a good balance for invoice AP (typically within 2 min of arrival) without hammering Graph. Use `1` for near-real-time; `5`–`10` for low-volume mailboxes.

Restart after adding secrets:

**Azure backends (venv — recommended):**

```powershell
cd backend
# restart uvicorn, celery worker, and celery beat
```

**Docker:**

```powershell
docker compose -f docker-compose.azure.yml build api worker beat
docker compose -f docker-compose.azure.yml up -d
# or local stack: docker compose build api worker beat && docker compose up -d
```

## Automatic polling

With `beat` and `worker` running, the inbox is polled every `GRAPH_POLL_INTERVAL_MINUTES` (default **2**). You only need `POST /api/process/trigger` for immediate runs or testing.

## Test

1. Send an email to the mailbox with a PDF attachment named like `invoice.pdf`
2. Wait for the next beat cycle, or trigger immediately:

```powershell
Invoke-RestMethod -Method POST http://localhost:8001/api/process/trigger
```

3. Check:
   - `GET /api/invoices` — new `pending` row
   - `GET /api/audit-log` — `email_ingested` or `email_skipped`
   - Message moved to **Processed** or **Exceptions** folder (Phase 6), or marked read if folder moves are disabled

## Without Graph

Leave Graph env vars empty. `poll_inbox()` returns `[]` and manual `POST /api/invoices/upload` still works.
