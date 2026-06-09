# Phase 2 — Azure Blob storage + vendor registry

Phase 2 stores invoice PDFs in **Azure Blob Storage** when configured, routes files by **email sender** via a vendor registry, and optionally relocates `unknown` blobs after parsing.

## Blob layout

After ingest and parsing, PDFs are stored in the **vault folder layout**:

```text
{container}/invoice/{org}/{vendor}/{year}/{month}/{invoice_no}_{date}.{ext}
```

Example:

```text
invoices/invoice/HvOrg/Atlassian Pty Ltd/2026/May/INV-042_2026-05-04.pdf
```

- `{org}` — PascalCase org slug (e.g. `HvOrg` from `hv-org`)
- `{vendor}` — display name (e.g. `Atlassian Pty Ltd`), not a slug prefix
- `{year}` / `{month}` — from invoice date; month is the full name (e.g. `May`)
- `{ext}` — preserved from the original upload (`.pdf`, `.jpg`, etc.)

At first upload (before parse), files may land on a temporary path; `_post_parse_relocate` in the pipeline moves them to the vault layout once vendor and date are known.

Stored path in the database uses the URI form:

```text
azureblob://invoices/invoice/HvOrg/Atlassian Pty Ltd/2026/May/INV-042_2026-05-04.pdf
```

When `AZURE_STORAGE_CONNECTION_STRING` is unset, files fall back to `UPLOAD_DIR` under the same `invoice/...` relative path.

## Vault API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/vault/tree` | Org → vendor → year → month tree + file list |
| POST | `/api/vault/migrate` | Admin: relocate legacy blobs into vault layout |

Legacy blobs under `{org-slug}/{vendor-slug}/incoming/...` can be migrated with `POST /api/vault/migrate`.

Rejected invoices are stored separately:

```text
rejected/{org}/{vendor}/{year}/{month}/{invoice_no}_{date}.{ext}
```

Reject via `POST /api/approvals/{id}/reject` (exception or processed invoices). Rejecting a **processed** invoice clears journal/posting data, moves the file to `rejected/...`, and removes it from vault exports. Approve from rejected restores the file to `invoice/...` before reprocessing.

## Vendor slug at ingest

At email ingest, the sender address is matched against `vendor_registry.sender_pattern`:

| Pattern | Matches |
|---------|---------|
| `billing@atlassian.com` | Exact email |
| `@atlassian.com` | Any address on that domain |

Unmatched senders use slug `unknown`.

After parse, if `BLOB_AUTO_RELOCATE_UNKNOWN=true` (default), the blob is moved when the parsed vendor resolves to a different slug than at ingest. Rule-book vendors use the matching `vendor_registry.vendor_slug` (e.g. parsed “Qantas” → `qantas/`, not sender-based `deloitte-touche-tohmatsu/`). Unmatched vendors stay on sender slug or `unknown/`.

## Vendor registry API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/vendors` | List registry entries |
| POST | `/api/vendors` | Add vendor (slug, name, sender pattern, optional ABN, approved flag) |
| PATCH | `/api/vendors/{id}` | Update approval, ABN, sender pattern |

Seed defaults (from rule-book vendor names):

```powershell
docker compose exec api python seed.py
```

Or vendors only on an existing DB:

```powershell
docker compose exec api python -c "import asyncio; from seed import seed_vendors_only; asyncio.run(seed_vendors_only())"
```

## VR05 — approved vendor ABN

When the PDF ABN fails checksum validation, VR05 checks **approved** registry entries matched by sender or vendor name. If the registry has a valid ABN, validation passes and the invoice uses that ABN.

Example: invoices with OCR typo ABN can pass when the sender matches an **approved** registry entry with a valid ABN.

## Environment variables

```env
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER=invoices
BLOB_AUTO_RELOCATE_UNKNOWN=true
BLOB_AUTO_LEARN_SENDER=true
```

Add these to `backend/.env` (Docker loads via `env_file` in `docker-compose.yml`).

## Enable blob storage locally

1. Paste connection string into `backend/.env`
2. Rebuild and restart:

```powershell
docker compose build api worker
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec api python -c "import asyncio; from seed import seed_vendors_only; asyncio.run(seed_vendors_only())"
```

3. Trigger ingest or upload a PDF — `raw_file_path` should start with `azureblob://`

## Auto-learn sender

When `BLOB_AUTO_LEARN_SENDER=true`, a successfully **processed** invoice with a known slug and email sender adds a new registry row (`approved=false`) if no matching pattern exists yet. Review and approve via `PATCH /api/vendors/{id}`.

## Audit events

| Event | When |
|-------|------|
| `blob_relocated` | Blob moved to vault layout after parse |
| `vault_migrated` | Bulk migrate relocated org blobs to vault layout |
| `invoice_rejected` | User rejected; blob moved to rejected/ tree |
| `invoice_approved` | Approved for reprocess (restores rejected/ → invoice/ when needed) |
| `vendor_sender_learned` | New sender pattern recorded after processed |
