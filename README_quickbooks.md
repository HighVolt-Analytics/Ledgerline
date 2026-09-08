# QuickBooks Online — analysis and implementation plan

Handshake (Connect → Intuit login → sandbox company) is done. This note covers **what we send today for Xero**, **what QuickBooks Online (QBO) actually requires**, **whether current environment variables and OAuth scopes are enough**, and **how we will implement bill export without changing field extraction**.

**Shipped in this stage:** a tenant can have only **one** of Xero or QuickBooks connected (connecting one disconnects the other). Pulled contacts loads **QBO vendors and customers** when QuickBooks is connected; **Add contact** creates a Vendor or Customer in QBO (`DisplayName` + type required). Settings → Tax lists **QBO TaxCode** rows (sync + create via TaxService). Settings → Chart of accounts shows **local** and **QuickBooks** tables with push/pull/sync; sub-ledgers write as QBO subaccounts (`ParentRef`). Company currencies are cached on connect (`qbo_currencies`); a missing ISO is created in QBO only when Multicurrency is already on. Bill export is not in this stage.

LedgerLink already extracts AP bills into Postgres. Xero export only **forwards those fields**. QBO must do the same: no second extraction pipeline, no Settings mapping grid.

Package layout for the code (when we build it) stays under `backend/app/integrations/qbo/`, matching `backend/app/integrations/README.md`. This file is the product/API plan.

Official references:

- [OAuth scopes](https://developer.intuit.com/app/developer/qbo/docs/learn/scopes)
- [Bill entity](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/bill)
- [Vendor](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/vendor)
- [Account (incl. subaccounts)](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account)
- [Tax (non-US / global)](https://developer.intuit.com/app/developer/qbo/docs/workflows/calculate-sales-tax/automated-sales-tax-for-non-us-locales)
- [Attachments](https://developer.intuit.com/app/developer/qbo/docs/workflows/attach-images-and-notes)

---

## 1. What is already true in LedgerLink

Invoice processing does **not** depend on Xero or QBO. A bill can reach `processed` with extracted fields even when accounting is disconnected.

Fields we already store and that Xero uses (same source for QBO):

| LedgerLink field | Typical source | Xero use today |
|---|---|---|
| `invoices.vendor` | Extraction | Match or **create** Contact; required if no Contact exists |
| `invoices.abn` | Extraction | Contact tax id match |
| `invoices.email_sender` | Capture | Contact email match |
| `invoices.account_code` / `account_name` | Mapping / Post to | Header GL; must exist on the Xero org (we do **not** create GL) |
| `line_items.parent_ledger`, `line_items.sub_ledger` | Line GL / sub-ledger | Sent as Xero `AccountCode` (leaf code when sub-ledger is set) |
| `invoices.gst`, `invoices.gst_rate` | Extraction | Xero AP `TaxType`: `INPUT` if tax ≠ 0, `EXEMPTINPUT` if tax = 0 |
| `invoices.currency` | Extraction | ISO code; org must have that currency enabled |
| `invoices.invoice_no` | Extraction | Xero `InvoiceNumber` |
| `invoices.invoice_date`, `due_date` | Extraction | `Date` / `DueDate` |
| `invoices.cost_centre` | Extraction | Xero tracking — **deferred**; do not block QBO on this |
| PDF / stored file | Capture | Xero attachment after create |
| Sales / ACCREC | Route | **Out of scope** (same as Xero Phase 1) |

Xero contact rule (important): we do **not** require the supplier to exist in Xero before export. We search (mapping → ABN → exact name → email). If none and `vendor` is non-empty, we **create** a supplier Contact. If the name is missing, export is blocked (`contact_not_mapped`). Ambiguous name matches are blocked for human review.

QBO has **no unclassified Contact**. Vendor and Customer are separate objects (`DisplayName` unique across Vendor, Customer, and Employee). Document types now have **Counterparty type** (Vendor or Customer). After a document is processed, we write that extracted name into QBO as the matching object (create if missing). An AP **Bill** still only accepts `VendorRef`. Settings → Add contact still asks Vendor vs Customer for manual creates.

GL and tax rates are **not** auto-created. Currency is sent as ISO. On QBO we POST `CompanyCurrency` when the code is missing **and** `Preferences.CurrencyPrefs.MultiCurrencyEnabled` is already true. Multicurrency **cannot** be turned on through the API; if the document ISO ≠ home currency and the toggle is off, we block (409) and tell the user to enable it in QuickBooks (Settings → Account and settings → Advanced).

---

## 2. Environment variables and scopes

### Scopes

QBO accounting is **one scope**, not a Xero-style list (`accounting.invoices`, `accounting.contacts`, …).

| Scope | Needed for AP bills? |
|---|---|
| `com.intuit.quickbooks.accounting` | **Yes.** Covers Vendor, Account, TaxCode, CompanyInfo, Preferences, Bill, Attachable/upload. This is already the default (`QUICKBOOKS_OAUTH_SCOPES`). |
| `com.intuit.quickbooks.payment` | **No.** Card/ACH processing only. |
| `openid` / `profile` / `email` | **No** for bills. Optional later if we want Intuit user profile. |

If Connect already succeeded with `com.intuit.quickbooks.accounting`, **you do not need extra scopes** to create vendors, bills, or attach PDFs. Reconnect only if the Intuit app was created without Accounting selected.

### Variables already sufficient for handshake + later export

These are enough. Do not add `QBO_*` aliases.

| Variable | Role |
|---|---|
| `QUICKBOOKS_ENABLED` | Feature flag (same idea as `XERO_ENABLED`) |
| `QUICKBOOKS_CLIENT_ID` / `QUICKBOOKS_CLIENT_SECRET` | Intuit app keys |
| `QUICKBOOKS_REDIRECT_URI` | Must match the developer portal **exactly** |
| `QUICKBOOKS_ENVIRONMENT` | `sandbox` → `sandbox-quickbooks.api.intuit.com`; production → `quickbooks.api.intuit.com` |
| `QUICKBOOKS_OAUTH_FRONTEND_RETURN_URL` | After callback, UI at `/integrations` |
| `QUICKBOOKS_OAUTH_SCOPES` | Optional; default is already `com.intuit.quickbooks.accounting` |

**Not required** for Phase 1 export:

- Extra Intuit keys
- A second redirect URI for API calls (tokens go to the same callback)
- Webhook keys (later, for inbound QBO events)

Token crypto uses the existing JWT/app secret, same pattern as Xero. Refresh tokens are stored on `accounting_integrations` (`provider_tenant_id` = Intuit `realmId`).

---

## 3. QBO vs Xero: objects we will post

| LedgerLink / Xero | QuickBooks Online | Notes |
|---|---|---|
| Contact (supplier) | **Vendor** | Bill cannot use a Customer. `VendorRef.value` is the QBO **Id**, not the display name. |
| ACCPAY Invoice, `Status=DRAFT` | **Bill** | QBO has **no Draft bill** equivalent. A successful POST is an unpaid AP bill the accountant can see. Product choice: still auto-push after `processed`, same as Xero, and document that QBO is immediately “open”, not draft. |
| `AccountCode` (string code) | **Account.Id** | QBO posts by internal Id. `AcctNum` / `FullyQualifiedName` are for matching our codes/names after sync. |
| `TaxType` `INPUT` / `EXEMPTINPUT` | **TaxCodeRef** (line) + `GlobalTaxCalculation` | Cannot copy Xero codes. Must use tax codes that exist **in that company**. US companies often use `TAX` / `NON`; AU/UK/global companies require a real purchase TaxCode on **every** line. |
| Tracking categories | **Class** (line) / **Department** (whole bill) | Same as Xero tracking: **not in Phase 1**. |
| CurrencyCode | **CurrencyRef.value** (ISO) | Home currency always OK. Foreign ISO: Multicurrency must already be on in QBO UI; we then POST `CompanyCurrency` `{ "Code": "EUR" }` if missing. |
| InvoiceNumber | **DocNumber** | QBO max length **21**. Truncate or hash if our invoice number is longer. |
| Attachment | **POST …/upload** (Attachable) | After Bill `Id` exists. Multipart metadata + file. Accounting scope is enough. |

QBO **does** support subaccounts: `Account.SubAccount=true` and `Account.ParentRef`. That is the analogue of LedgerLink parent ledger + sub-ledger. Bills must post to the **leaf** account Id (the subaccount), not the parent, when a sub-ledger is chosen.

---

## 4. Mandatory fields and guardrails

### 4.1 Not mandatory in our database for processing

Extraction and pipeline do not require QBO (or Xero) to be connected. Empty `account_code`, missing GST, or missing vendor can still exist as exceptions/validation in LedgerLink. Accounting export is a **later gate**.

### 4.2 Mandatory for a QBO Bill POST (Intuit)

Hard API requirements:

1. **`VendorRef.value`** — Id of an **existing** Vendor. You cannot pass only a name on Bill. If the vendor is missing, we create Vendor first (same as Xero Contact create), then POST Bill.
2. **`Line`** — at least one line.
3. Each expense line: **`Amount`**, **`DetailType` = `AccountBasedExpenseLineDetail`**, **`AccountBasedExpenseLineDetail.AccountRef.value`**.
4. That account must exist and be a type QBO allows on bills (typically Expense / Cost of Goods Sold / Other Expense — not a bank account). Prefer posting to the **leaf** subaccount Id.

Strongly required in practice (region / company settings):

5. **Tax (global / AU / UK):** every purchase line needs **`TaxCodeRef`**. Intuit: tax cannot be turned on via API; `Preferences.TaxPrefs.UsingSalesTax` must already be true in the company. US companies often put tax at transaction level; do not assume one tax strategy for sandbox vs AU production.
6. **Currency:** if `invoices.currency` ≠ company home currency, Multicurrency must already be on in the QBO company (API cannot enable it). We then add the ISO via `POST companycurrency` if it is not already listed. Same rule as Xero: **do not silently substitute AUD/USD**.
7. **`TxnDate` / `DueDate`:** not always strictly required (QBO may default today); we still send extracted dates when present.

Vendor create (when we auto-create):

- **`DisplayName`** required and unique in the company.
- Optional: `TaxIdentifier` ← ABN, `PrimaryEmailAddr`, `BillAddr` from extraction.
- Do **not** invent a vendor if `invoices.vendor` is blank.

### 4.3 Guardrails we will enforce in LedgerLink (before POST)

Mirror Xero `validate_invoice_for_xero_export`, QBO-named:

| Block code | Condition |
|---|---|
| `accrec_not_supported` | Sales route — no QBO Invoice/Customer in Phase 1 |
| `vendor_not_mapped` | No DisplayName to match or create |
| `ambiguous_vendor_match` | More than one Vendor on exact name/ABN (human review) |
| `account_not_mapped` | No GL / sub-ledger that matches a synced QBO Account Id |
| `tax_code_not_mapped` | Global tax company and we cannot resolve a purchase TaxCode from GST amount/rate |
| `currency_missing` / `currency_not_supported` | Same policy as Xero |
| `qbo_not_ready` | Not connected, missing `realmId`, or token refresh failed |

Processing without QBO stays allowed. Auto-push runs only when QBO is connected (same commit-flush pattern as Xero; never fire-and-forget on Celery `asyncio.run()`).

### 4.4 Other Intuit limitations

- Rate limit: on the order of **500 requests per minute per realm**. Batch sync of Vendor/Account/TaxCode; do not query per line in a tight loop without cache.
- Query language: `SELECT * FROM Vendor WHERE DisplayName = '…'` (escape quotes). Pagination via `STARTPOSITION` / `MAXRESULTS`.
- Updates need **`Id` + `SyncToken`** (sparse update). Create-only for Phase 1 bills is simpler (idempotency via our export ledger, not QBO update).
- Sandbox data can be reset; **never hard-code Account/Vendor Ids**.
- Public listing of the Intuit app needs [app assessment](https://developer.intuit.com/app/developer/qbo/docs/go-live/app-assessment); sandbox development does not.

---

## 5. Sub-ledgers vs QBO chart of accounts

LedgerLink already assigns **parent ledger + optional sub-ledger** on `line_items`. That is our dimension; we do not invent a new one for QBO.

QBO model:

- Chart of accounts is a **tree**. Child accounts have `ParentRef` and `FullyQualifiedName` like `Operating Expenses:Software`.
- A Bill line has **one** `AccountRef` — the account you debit. If the user picked a sub-ledger, that must be the **child** account Id.
- If sub-ledger is **None** (explicit), post to the **parent** account Id, same as Xero posting to parent code.
- If the QBO company has **no** subaccounts under that parent, posting to the parent is valid; we must not invent child accounts.

Implementation rule (same as Xero “codes must exist”):

- Sync QBO Account list into tenant tables (`Id`, `Name`, `AcctNum`, `FullyQualifiedName`, `ParentRef`, `AccountType`, `Active`).
- Resolve: `parent_ledger` + `sub_ledger` → one Account Id by `AcctNum` or exact `FullyQualifiedName` / name.
- **Do not** auto-create expense accounts or subaccounts in Phase 1 (Xero does not create GL either).

Class/Department are **not** sub-ledgers. They are optional tracking. Deferred with Xero tracking.

---

## 6. Tax: why Xero’s INPUT/EXEMPTINPUT cannot be reused

Xero AU AP uses system tax types `INPUT` / `EXEMPTINPUT`. QBO tax codes are **company-specific Ids** (often numeric strings) with a **purchase** rate list.

Plan:

1. Sync `TaxCode` (and rates) after connect.
2. Detect locale from `CompanyInfo.Country` / tax preferences.
3. Map extracted GST:
   - GST amount or rate **zero** → purchase tax code that is GST-free / out of scope / 0% (query by rate, not by Xero name).
   - Non-zero GST → purchase tax code whose purchase rate matches `gst_rate` (e.g. 10% AU).
4. If several codes match, prefer Active + purchase-applicable; if still ambiguous, block (`tax_code_not_mapped`) rather than guess.
5. Send `GlobalTaxCalculation`: `TaxExclusive` to match how we treat Xero `LineAmountTypes=Exclusive`, unless we later prove inclusive invoices need `TaxInclusive` (Intuit is picky: inclusive amounts often need exclusive line amounts plus tax detail).

US sandbox companies may only need `NON` / `TAX`. AU production will fail if we omit `TaxCodeRef`. Branch on company prefs, not on `QUICKBOOKS_ENVIRONMENT`.

---

## 7. Root-cause analysis (what will break if we “just POST like Xero”)

| If we copy Xero blindly | What QBO does |
|---|---|
| POST `Contact.ContactID` | Bill rejects; needs `VendorRef` |
| POST `AccountCode: "200"` | Ignored/invalid; needs `AccountRef.value` = Id from sync |
| POST `TaxType: "INPUT"` | Invalid; must be that company’s TaxCode Id |
| POST `Status: "DRAFT"` | Not a Bill field; bill is live AP |
| Assume vendor must exist and never create | Stricter than our Xero product; we **will** create Vendor by name like Contact |
| Assume vendor must exist and we refuse create | Extra guardrail — **not** our Xero behaviour; do not add unless product asks |
| Use header `account_code` only, ignore line `sub_ledger` | Posts to parent; P&L by subaccount is wrong |
| Send full invoice number as `DocNumber` | Fail or truncate at 21 characters |
| Skip tax on AU company | Validation / tax calculation errors (often code 6000) |
| Fire-and-forget export on Celery | Same class of bug we already fixed for Xero |
| New mapping UI | Rejected; codes must exist in QBO after sync |

Handshake-only does **not** prove export: sandbox sample vendors/accounts/tax may not match extracted `account_code` / GST. First real work after this plan is **sync master data**, then **one Bill** in sandbox.

---

## 8. Plan of approach (implementation order)

Do not start bills until each step is green.

### Phase 0 — done

OAuth connect/callback, `realmId` on `accounting_integrations`, Connect/Disconnect on Integrations, env names above.

### Phase 1 — package + readiness (no bills yet)

Add `backend/app/integrations/qbo/` (oauth/tokens/store/client). `require_qbo_ready` like `require_xero_ready`. Token refresh. CompanyInfo read to store display name / country / home currency.

### Phase 2 — sync (read-only into our DB)

Pull and cache: Account (with parent/subaccount), Vendor, TaxCode, CompanyCurrency. On connect we sync listed currencies plus home currency. Missing foreign ISO is **created** with `POST /companycurrency` only when Multicurrency is already enabled in the QBO UI. Integrations UI can later show synced lists like Xero (no mapping grid). Tenant isolation by `realmId`.

### Phase 3 — resolve + validate

Vendor: stored mapping → TaxIdentifier (ABN) → exact DisplayName → email; else create Vendor when `vendor` is set.  
Account: parent + sub-ledger → Account Id.  
Tax: GST → TaxCode Id.  
Currency: ISO vs company; `ensure_qbo_currency` (wired at Bill export later).  
Sales documents: skip.

### Phase 4 — export Bill + PDF

Build Bill JSON from **existing** invoice/line fields. POST `/v3/company/{realmId}/bill`. Write export ledger (pending/success/failed) like Xero Acc sync. Upload PDF. Auto-push after successful invoice commit only if QBO connected.

Idempotency: one successful Bill per invoice (or per content fingerprint); do not create duplicates on retry.

### Phase 5 — not now

Customer invoices, BillPayment, JournalEntry, Class/Department, creating GL/subaccounts, Intuit webhooks, production app assessment, Payments API.

---

## 9. Example Bill shape (account-based AP)

Illustrative only; Ids come from **that** sandbox after sync.

```json
{
  "VendorRef": { "value": "56" },
  "DocNumber": "INV-1001",
  "TxnDate": "2026-09-01",
  "DueDate": "2026-09-30",
  "CurrencyRef": { "value": "AUD" },
  "GlobalTaxCalculation": "TaxExclusive",
  "PrivateNote": "QLL:<invoice_id>",
  "Line": [
    {
      "Amount": 100.00,
      "Description": "Line from extraction",
      "DetailType": "AccountBasedExpenseLineDetail",
      "AccountBasedExpenseLineDetail": {
        "AccountRef": { "value": "80" },
        "TaxCodeRef": { "value": "11" }
      }
    }
  ]
}
```

`AccountRef` `80` is the **subaccount** Id when `line_items.sub_ledger` resolved; otherwise the parent expense account Id.

---

## 10. Decision summary

- **Env vars you have are enough** for handshake and for later accounting API calls. No extra Intuit secrets.
- **Scope `com.intuit.quickbooks.accounting` is enough** for vendors, COA, tax, bills, attachments. Do not add Payments.
- **Our DB does not store QBO-mandatory Ids** until we sync. Extraction fields stay as they are; export **resolves** them to Vendor Id, Account Id, TaxCode Id.
- **Vendor need not pre-exist** if we have a legal name (we create it). **GL and tax codes must already exist** in QBO.
- **Sub-ledgers are supported** in QBO as subaccounts; we post to the child Account Id.
- **QBO bills are not drafts**; treat that as a product difference from Xero ACCPAY DRAFT, not as a missing API field we can set.
- **Tracking / Class** stays deferred. **Sales invoices** stay out of scope.
