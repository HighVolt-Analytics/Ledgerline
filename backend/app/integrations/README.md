# Accounting integrations

Vendor-agnostic helpers live in `core/`. Each accounting product gets its own package next to `xero/`. HTTP routes stay in `app/api/`. SQLAlchemy tables stay in `app/models/`.

This is the only README for this layer. Copy the Xero package when adding another provider.

## Layout

```text
app/integrations/
  core/                 # shared by every provider
    oauth_state.py      # signed OAuth state + JTI consume
    token_crypto.py     # encrypt/decrypt access and refresh tokens
    canonical.py        # optional invoice snapshot helper
    dispatch.py         # optional multi-adapter send (Xero only today)
  xero/                 # first provider — follow this shape
    oauth.py            # authorize URL, token exchange
    tokens.py           # refresh and valid access token
    store.py            # persist connection + require_xero_ready
    connect_api.py      # connect/callback helpers
    client.py           # Accounting API (export, sync, master writes)
    http_legacy.py      # retry client used by verify/reconcile
    errors.py           # transient / recoverable / terminal buckets
    sync.py             # pull org, accounts, tax, currencies, contacts
    sync_jobs.py        # job enqueue / status
    sync_counts.py      # sync counters + payload hash
    background_sync.py  # scheduled pull
    accounts.py         # chart of accounts read/write
    account_types.py    # LedgerLink type ↔ Xero type
    tax_rates.py        # tax rates + AP TaxType (INPUT / EXEMPTINPUT)
    currencies.py       # ensure document currency on the org
    contacts.py         # match or create supplier contact
    mapping.py          # older mapping gate (internal; no Settings UI)
    export.py           # ACCPAY DRAFT export + ledger evidence
    accpay.py           # Xero bill payload
    attachments.py      # PDF attach
    auto_push.py        # after processed AP bill commits
    push.py             # thin wrap for /invoices/{id}/push
    master_data.py      # list cached Xero rows
    organisation_isolation.py
    verify.py / readiness.py / reconcile.py
```

## Rules for a new provider (for example QBO)

1. Add `app/integrations/<provider>/` with the same roles: oauth, tokens, store, client, sync, export.
2. Do not put provider HTTP inside `core/`. `core/` stays OAuth state and token crypto only.
3. Do not add a Settings mapping grid. Codes on the document must already exist in the remote org (contact may be created; GL and tax must exist; currency is sent as ISO and must be enabled on the org).
4. Keep FastAPI routers in `app/api/` and tables in `app/models/`.
5. Auto-export only after a successful invoice transaction commit. Never fire-and-forget on a Celery `asyncio.run()` loop.
6. Connection readiness is one function in that provider’s `store.py` (Xero: `require_xero_ready`). Re-export it if an older service still imports it.

## Xero runtime path

Connect OAuth → select organisation → **Sync settings** / **Sync contacts** → process AP bill → auto-push ACCPAY Draft → export queue / export evidence for failures.

Do not add a second copy under `app/services/integration/<provider>/`. That pattern was removed.
