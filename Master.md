# Integrations layer — master plan (rebuild)

This is the entry point. Stage files live in [docs/xero-plan/](docs/xero-plan/).

**This is a new Integrations layer**, not a patch of the current Xero services. Old integration code is **not** used. When the new path is wired, old modules are **commented out** (then removed). `Temp.md` and the Xero field spreadsheet describe **how Xero’s API works**, not our folder layout.

---

## Decisions (locked)

| Topic | Choice |
|--------|--------|
| v1 destination | **Xero only**. Other adapters ignored for now. |
| Canonical data | **A** — read **existing** invoice / vendor / lines / PDF in Postgres. No new extraction engine. Extra fields later if a destination needs them. |
| UI | **No UI changes.** Existing **Connect Xero** must work against **new** backend. Same routes the frontend already calls. |
| Shared layer | Thin **`Integrations/core/`** |
| OAuth split **5b** | **B** — generic OAuth helpers in **core**; Xero URLs, scopes, token HTTP, Xero tenant id in **`Integrations/xero/`** |
| Connect behaviour **5a** | **A** — tenant **admin** OAuth; tokens stored **per LedgerLink tenant** (not one global Xero login) |
| Old code | Do not call it. Comment out when cutting over. |
| Future send | Architecture allows **one document → several adapters**. v1 only implements the Xero adapter. |

---

## How to read the other files

| Order | File | When |
|-------|------|------|
| 0 | [00-you-must-provide.md](docs/xero-plan/00-you-must-provide.md) | **You** — Xero app + secrets. Blocks Connect. |
| 1 | [01-architecture.md](docs/xero-plan/01-architecture.md) | Folders, core vs xero, payload union, cutover. |
| 2 | [02-connect-oauth.md](docs/xero-plan/02-connect-oauth.md) | **First build:** Connect click → tokens stored. |
| 3 | [03-after-connect.md](docs/xero-plan/03-after-connect.md) | Org select, sync, map, export — **after** Connect works. Not this sprint unless we agree. |
| 4 | [04-you-vs-implementer.md](docs/xero-plan/04-you-vs-implementer.md) | Who provides what, before which step. |

Ignore previous “extend existing `app/services/integration/xero`” wording if you still see it in git history; **this Master is the spec**.

---

## Target layout (backend)

Names can shift slightly on implementation; the split must not.

```
backend/app/integrations/          # or backend/integrations/ — pick one tree, keep it
  core/                           # shared, vendor-agnostic
    oauth_state.py                # CSRF state, Redis/JWT
    token_crypto.py               # encrypt/decrypt at rest
    dispatch.py                   # later: send(document, [adapters])
    canonical.py                  # read existing invoice → dict of our fields
  xero/
    oauth.py                      # authorize URL, token exchange, connections API
    client.py                     # Bearer + xero-tenant-id REST
    connect_api.py                # handlers used by existing routes
    ...                           # later: accpay payload, sync
```

- **`.env`**: combined file (`XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI`, …). No separate Xero env file required.
- **HTTP paths stay as today** so the UI does not change, e.g. `GET /api/integrations/xero/connect`, `GET /api/integrations/xero/callback`. Implementation imported from `integrations.xero`, not from old services.

---

## Build order

1. You complete Stage 0 (Xero portal + secrets in `.env`).  
2. Implement **core** (state + crypto) + **xero oauth** + wire **existing** connect/callback routes. Comment out old connect handlers.  
3. Prove: click Connect → Xero → back on Integrations, tokens in DB for that tenant.  
4. Stop. Org picker / sync / export are Stage 3 — only after this is green.

---

## Out of scope until after Connect

- New extraction pipeline  
- New Integrations UI  
- QuickBooks / other folders (dispatch may be a stub that only calls Xero)  
- Rebuilding mapping workspace  
- Implementing every spreadsheet object  

---

## Flaw rule

If Connect fails, debug **portal URI, `.env`, new oauth code, API up, admin JWT**. Do not resurrect old Xero services to “just make it work.”
