# Xero write-back (backend plan)

**Frontend is out of scope here.** This file is the backend work after handshake is already live.

Connect (OAuth) already requests write-capable scopes (`accounting.contacts`, `accounting.settings`, `accounting.invoices`, `accounting.attachments`). Today we mostly **read** (sync) and **write bills** (ACCPAY draft). This plan adds **write of masters**: when LedgerLink **creates** a vendor (contact) or a **GL account**, the same record must be created **in Xero**, then stored in our Xero cache tables.

Keep existing Stage 3–4 notes for the current backend wiring:

- [docs/xero-plan/03-after-connect.md](docs/xero-plan/03-after-connect.md) — sync, canonical, ACCPAY export  
- [docs/xero-plan/04-you-vs-implementer.md](docs/xero-plan/04-you-vs-implementer.md) — who provides secrets / webhooks later  

---

## Goal

| LedgerLink action | Xero write | Then locally |
|-------------------|------------|----------------|
| New **vendor** (Contacts list / promote pending) | `POST /Contacts` | Upsert `xero_contacts` (and keep vendor master) |
| New **GL row** (chart of accounts save) | `PUT`/`POST /Accounts` | Upsert `xero_accounts` |

**Not in this backend slice:** tax-rate catalogue write (we have no vendor-like tax table); employee/customer → Xero (AP path uses **suppliers**); UI wiring (later).

**Already exists (reuse, do not duplicate):** `XeroApiClient.post_json`, token refresh, `create_xero_supplier_contact` during **invoice export** when a contact is missing. Promote that into a **shared** “ensure Xero contact” used by both export and vendor-create.

---

## Prerequisites (already true)

- Tenant admin OAuth; tokens encrypted; `provider_tenant_id` selected.  
- `accounting.contacts` — create/update contacts.  
- `accounting.settings` — create/update chart of accounts (not `.read` only).  
- Sync still used to **refresh** after writes and to detect collisions.

If a write returns 403, scopes or the Xero app grant are wrong — not a UI bug.

---

## 1. Shared Xero write helper module

Add something like `backend/app/integrations/xero/masters.py` (name can vary). **Do not** import legacy `xero_token_service`. Use `XeroApiClient` + `require_xero_ready`.

Functions (async, `db`, `tenant_id`):

1. **`ensure_xero_contact(...)`**  
   - Input: legal name (required), optional email, ABN/`TaxNumber`, `IsSupplier=true`.  
   - If Xero not connected: raise a clear error (caller decides: fail the LedgerLink save vs save-local-only). **Recommendation:** if Xero is connected, **write is mandatory** so the two systems do not diverge. If not connected, save LedgerLink only.  
   - Dedupe: search synced `xero_contacts` by normalised name and/or tax number; if unique match, **do not POST**; return existing `ContactID`.  
   - Else `POST Contacts` with `{ "Contacts": [ { "Name", "IsSupplier", "EmailAddress?", "TaxNumber?" } ] }`.  
   - Persist row on `XeroContact` (same as export create-contact today).  
   - Export path should call this instead of a second HTTP implementation.

2. **`ensure_xero_account(...)`**  
   - Input: code, name, LedgerLink type (`Expense` / `Asset` / …).  
   - Map type → Xero `Type` (`EXPENSE`, `CURRENT`, `CURRLIAB`, `SALES`/`REVENUE`, `EQUITY` — lock a mapping table in code).  
   - Default `TaxType`: e.g. `BASEXCLUDED` or `INPUT` for expenses (configurable constant; AU demo often uses BAS Excluded on COA).  
   - Dedupe: if `xero_accounts` already has this **code** for the selected org, skip POST.  
   - Xero: `PUT Accounts` (or POST per current Accounting API) with `Code`, `Name`, `Type`, `TaxType`.  
   - Persist `XeroAccount`.  
   - Xero **rejects some types** as system accounts; surface `XeroApiError` to the API.

3. **Idempotency / races**  
   - Unique Xero errors (“already exists”): treat as success, GET by code/name, upsert local cache.  
   - Optional Redis lock per tenant+code / tenant+name (same pattern as token refresh).

---

## 2. Hook LedgerLink create paths (backend only)

### Vendors

After a successful **create** or **promote pending → master** (vendor registry / vendor master services — whichever Contacts actually writes):

- Call `ensure_xero_contact`.  
- On Xero failure: **rollback** the local create **or** mark the vendor `Pending` with `last_error` and do not treat as Active. Prefer **fail the request** so the UI can retry.  
- Do **not** rewrite vendor **bank** from Xero; we only create the contact shell.

**Do not** fire on every vendor **edit** in v1 (name change in Xero is a later PUT Contacts). v1 = **create only**.

### Chart of accounts

In `save_chart_of_accounts`:

- Diff **new codes** vs previous payload (and vs `xero_accounts` for this org).  
- For each **new** code, `ensure_xero_account`.  
- Updates/renames of existing codes: **v1 skip** (Xero PUT update later).  
- Deletes/archive: **v1 skip** (do not archive Xero accounts automatically).  
- If any Xero create fails, fail the whole save (or save local and return 207 — **prefer fail whole save**).

Bulk import of COA: same diff loop.

---

## 3. HTTP surface (backend)

Keep existing sync/export routes.

Add thin admin routes (UI later), e.g.:

- `POST /api/integrations/xero/contacts` — body name/email/tax; calls `ensure_xero_contact` (for tests and later UI).  
- `POST /api/integrations/xero/accounts` — body code/name/type; calls `ensure_xero_account`.

Vendor/COA existing endpoints (`POST /api/vendors`, `PATCH .../chart-of-accounts`) should **call the helpers internally** so the UI does not have to hit two APIs if we wire it that way later.

Auth: same as sync — **tenant admin**.

---

## 4. Sync after write

After a successful create, either:

- upsert the Xero payload into `xero_contacts` / `xero_accounts` from the POST response (minimum), or  
- trigger the existing settings/contacts sync for that entity.

Do **not** require the user to click Sync for the new row to exist in cache.

---

## 5. Tests (backend)

- Mock `XeroApiClient.post_json` / `put`: create vendor → Contacts POST called once; second create same name → no POST.  
- Create COA row → Accounts write; duplicate code → skip.  
- Xero 400 → LedgerLink create aborted.  
- Xero not connected → vendor/COA save still works (document in test).  
- Export still uses `ensure_xero_contact` (no double-create).

---

## 6. Order of implementation

1. Extract/shared `ensure_xero_contact` from export contact-create.  
2. `ensure_xero_account` + type map.  
3. Hook `save_chart_of_accounts` for **new** codes.  
4. Hook vendor **create/promote**.  
5. Optional explicit integration POST routes.  
6. Tests.

Frontend create-button behaviour comes **after** this.

---

## 7. Out of scope (this plan)

- Mapping UI removal / lookup-at-verify.  
- Writing **tax rates** into Xero.  
- Updating/deleting Xero masters.  
- ACCREC / employees.  
- Webhooks ([04](docs/xero-plan/04-you-vs-implementer.md)).
