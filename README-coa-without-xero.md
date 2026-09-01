# Chart of accounts without a Xero connection

This note answers a product question: **what breaks in LedgerLink if the chart of accounts behaved like tax rates** — shown only after a bill-processing platform (today: Xero) is connected, and **empty when there is no connection**.

Short answer: **do not do that.** Tax rates can wait for Xero. The chart of accounts cannot. LedgerLink journals, maps, and holds documents against a **local** GL catalogue that exists whether or not Xero is connected.

---

## Why tax rates can be empty, and COA cannot

**Tax rates** in Settings are a *platform tax table*. When Xero is disconnected, LedgerLink does not maintain a parallel “our tax codes” editor. The UI tells you to connect a bill-processing platform. Documents can still be captured, classified, and posted; tax *codes* used on a Xero bill are a write-side concern.

**Chart of accounts** is LedgerLink’s posting catalogue. It is seeded at tenant setup (`starter_chart_of_accounts`: bank, AR, AP, tax paid/collected, staff advance, operating expense, sales revenue, suspense). Invoices **pick** parents from it. Party **sub-ledgers** (vendor / customer / employee) hang under AP, AR, and advance. GL posting runs for **any posting document type**, not only Xero export.

Xero is an optional *mirror* of **parent** GL accounts. Sub-ledgers never go to Xero. Disconnecting Xero must **not** hide or wipe the local list — those rows are still the books LedgerLink posts to.

---

## What would break if COA were empty until Xero is connected

If Settings hid the catalogue, or if GET/PATCH returned no accounts whenever `xero_connected` is false, the following would fail or degrade. All of these read `rule_book_config.chart_of_accounts` (the same list `useChartOfAccounts` / `useCoaAccountOptions` expose).

### 1. Tenant setup and “books are ready”

New tenants get a starter COA so control names in posting defaults exist as real accounts. `coa_functional_for_journaling` is true only when payable, tax, fallback, bank, receivable, and “Tax Collected” all resolve **by name** in that list.

If the list is empty:

- Setup checklist item **Configure chart of accounts** never completes.
- Rule-book load will keep trying to merge starter accounts (or treat the tenant as not journal-ready).
- The product cannot honestly say the organisation can post.

### 2. Mapping and line GL

`resolve_category_for_config` looks up a ledger **name** in the COA. If there is no match, it returns **code `9999`** and keeps the name (or “Suspense Account” if the name is blank).

Empty COA means:

- Every mapped line is **unresolved / suspense-coded**.
- Invoice **Lines** (`LineGlAccountCell`) have **no parent GL dropdown**.
- Document-type **Post to** (`DocumentTypePostToSection`, `document_type_post_to_service`) cannot choose a ledger; saving a type that posts to a named account fails validation (“not in your chart of accounts”).
- Purchase / sales / expense / team-expense rules, vendor and customer default ledgers, employee expense accounts, bank narration rules, and bank-feed categorisation (`useCoaAccountOptions`) all show **empty selects**.

### 3. Journal generation and holds

Journals are built from COA codes and party sub-ledgers, not from “whatever Xero has today.”

If the catalogue is empty:

- Control accounts (AP, AR, tax, bank, suspense, staff advance) **do not resolve**. Pipeline already emits `journal_control_account_unresolved` and tells the user to pick the missing control ledger from the chart of accounts, then reprocess.
- Sales/purchase journals cannot debit/credit named control accounts.
- Settlement / team-advance journals cannot find parent or `EM-` child codes on the COA.
- Documents sit in **exception / mapping review** instead of posting.

This is independent of Xero. Vault-only, posting-number, PO–GRN, and SO–DN paths that **skip GL** would still work; **everything that posts a journal would not.**

### 4. Party sub-ledgers (AP / AR / advance)

Vendors, customers, and employees get **LedgerLink-only** children under payable, receivable, and staff-advance parents (`party_coa_subledger_service`). Those parents must exist on the local COA.

Empty COA means:

- Registering or promoting a vendor/customer/employee **cannot attach a sub-ledger**.
- Missing-sub-ledger **holds** stay on (or never get a parent to hang off).
- Even after you later connect Xero and pull GL parents, historical parties still have nowhere to live until those parents exist **locally**.

### 5. Posting defaults and Rule Book

`PostingDefaultsPanel` and `TeamExpensePostingPanel` bind payable, receivable, tax, bank, fallback, and advance accounts to **COA names**. Empty list ⇒ defaults are labels with no backing account. Rule Book validation then rejects Post-to ledgers that are not in the catalogue.

### 6. Department budgets and other masters

Department budgets require parent (and sub-GL) names that exist on the COA. Import fails with “not in your chart of accounts.” Employee masters that validate GL similarly fail.

### 7. Disconnect after you already posted

Worse than “never connected”: if connecting Xero **replaced** the local catalogue, and disconnect **cleared** it:

- Existing journals still point at old codes/names.
- Reprocess / remap / reversal cannot find those accounts.
- Party sub-ledgers orphan.
- Xero-linked parents that returned to the local table on Xero delete would vanish from LedgerLink even though they are still needed for history.

The current design is the opposite: **disconnect = one local table** (including former Xero-linked parents). Connect = local-only on top, full Xero GL below. Posting always uses the stored catalogue (`accounts` on GET), not “Xero cache only.”

---

## What would *not* break

These do not depend on a local COA being visible in Settings:

- Email ingest, OCR, classification, vault / understood documents.
- Tax **rate** UI (already gated on Xero).
- Xero OAuth itself.
- Document types that do not post GL.

You would still have a working capture product — not a working **ledger**.

---

## Practical consequences (no connection, empty COA)

| Area | If COA is empty whenever Xero is off |
| --- | --- |
| Settings → Chart of accounts | Nothing to edit; cannot seed books before Integrations |
| Invoice line GL | No accounts to pick; lines stay unmapped or suspense |
| Journals | Control accounts unresolved; posting held |
| Vendors / customers / employees | No AP/AR/advance parent for party sub-ledgers |
| Rule Book posting defaults & document types | Cannot bind Post to / tax / AR / AP |
| Bank feeds & narration rules | Empty ledger dropdowns |
| Department budgets | Parents/sub-GLs invalid |
| Tenant setup | “Configure chart of accounts” never done |
| Later Xero connect | You would have to invent the whole catalogue from Xero at once, then try to match history — high mismatch risk |

---

## Intended behaviour (keep this)

1. **Always** keep a local chart of accounts in rule-book config, with or without Xero.
2. Seed starter control accounts at tenant setup; admins edit them in Settings.
3. When Xero **is** connected, show two tables (local-only vs Xero GL). Push/pull/sync/delete talk to Xero for **parents only**.
4. When Xero **is not** connected, show **one** table of the same local catalogue (including accounts that used to be tagged Xero).
5. Never treat COA like tax rates (“connect a platform or this page is empty”). Tax is a platform table. COA is LedgerLink’s books.
