# LedgerLine partner authentication

Partner signup and sign-in are server-side. Demo booking (`/book-demo`) is unchanged and separate from the partner program.

## Journeys

| Journey | Entry | Backend |
|---|---|---|
| Demo booking | `/book-demo` and “Book a demo” CTAs | Existing shared booking API (`site=ledgerline`) |
| Partner program | `/partnership/signup`, `/partnership/signin` | PHP + SQLite under `/api/partners` |

After partner signup or sign-in, the browser opens the existing partner portal prototype. Portal commissions, Stripe, payouts and client checkout remain simulated.

## API

- `POST /api/partners/signup`
- `POST /api/partners/signin`
- `POST /api/partners/signout`
- `GET /api/partners/me`
- `GET /api/partners/admin/list` — **server-to-server only** for the HighVolt deployment portal

Passwords are stored only as `password_hash()` digests. Sessions use an HttpOnly cookie (`ll_partner_session`). Passwords are never written to `localStorage`.

### Admin partner list (deployment portal)

`GET /api/partners/admin/list` returns a read-only JSON list of partner accounts for operators. It is **not** public and is **not** authorized by partner session cookies.

Required header (either form):

- `Authorization: Bearer <PARTNER_ADMIN_TOKEN>`
- or `X-Partner-Admin-Token: <PARTNER_ADMIN_TOKEN>`

Response fields per partner: `name`, `email`, `firm`, `country`, `type`, `created` (YYYY-MM-DD).  
Never returned: passwords, `password_hash`, session ids, or the SQLite file.

If `PARTNER_ADMIN_TOKEN` cannot be loaded (env unset and private secrets file missing/invalid), the endpoint fails closed with `401`. The token is never logged or returned in API responses.

### Loading `PARTNER_ADMIN_TOKEN` on Hostinger

PHP checks sources in order:

1. `getenv('PARTNER_ADMIN_TOKEN')` (when available)
2. Else `private/partner-secrets.php` **beside** `public_html` (outside the document root)

The resolved secrets path must sit outside the document root; otherwise the API fails closed.

#### Hostinger File Manager steps

1. In hPanel → **Files** → **File Manager**, open the domain folder that contains `public_html` (not inside `public_html`).
2. Create a folder named `private` next to `public_html` if it does not exist.
3. Inside `private`, create `partner-secrets.php` with:

```php
<?php
declare(strict_types=1);

return [
    'PARTNER_ADMIN_TOKEN' => 'replace-with-a-long-random-secret',
];
```

4. Use a long random secret (for example `openssl rand -hex 32`). Use the **same** value as the deploy portal’s `LEDGERLINE_PARTNERS_ADMIN_TOKEN`.
5. Do **not** place this file under `public_html`, do **not** commit it to git, and do **not** put the secret in frontend code.
6. Confirm the API fails closed (`401`) if the file is removed or returns an empty token.

## Local development

Requires PHP 8+ with the `pdo_sqlite` extension. `npm run partner-api` and Vite auto-enable SQLite for common Windows WinGet PHP installs that ship without a `php.ini`.

```bash
npm run partner-api
# or rely on Vite, which starts PHP on 127.0.0.1:8791 and proxies /api/partners
npm run dev
```

Optional env:

- `PARTNER_DB_PATH` — absolute path to the SQLite file (default `public/api/data/partners.sqlite`; Vite/dev uses `partners.dev.sqlite`)
- `PARTNER_SESSION_COOKIE` — cookie name (default `ll_partner_session`)
- `PARTNER_SESSION_TTL_SECONDS` — session lifetime (default 14 days)
- `PARTNER_ADMIN_TOKEN` — shared secret for `GET /api/partners/admin/list` (preferred when you can set env)
- `PARTNER_DOCUMENT_ROOT` — test/local override for document root when resolving `../private/partner-secrets.php`
- `PHP_BIN` — PHP executable for Vite/tests
- `PHP_EXTENSION_DIR` — override extension directory when enabling `pdo_sqlite` locally

Local file fallback (when env is unset): place `private/partner-secrets.php` beside the Vite/`php -S` document root (`public/`), i.e. at the repo root under `private/`. That path is gitignored.

## Connecting the HighVolt deployment portal

Do **not** change production from this PR. To wire the portal Partners tab after both PRs are ready:

| Where | Variable / file | Purpose |
|---|---|---|
| Ledgerline (Hostinger) | `PARTNER_ADMIN_TOKEN` **or** `private/partner-secrets.php` | Shared secret that authorizes the admin list |
| Deploy portal (Vercel) | `LEDGERLINE_PARTNERS_API_BASE` | Origin only, e.g. `https://www.quantumledgerline.com` (no path) |
| Deploy portal (Vercel) | `LEDGERLINE_PARTNERS_ADMIN_TOKEN` | Same value as the Ledgerline admin token |

The portal BFF calls `{LEDGERLINE_PARTNERS_API_BASE}/api/partners/admin/list` with the Bearer token. The browser never receives the token or the SQLite path.

## Production configuration still needed

Do **not** change these from this PR. Before enabling partner auth in production:

1. **PHP** enabled for `quantumledgerline.com` document root (Hostinger).
2. **Writable data directory** for SQLite, preferably outside the web root, via `PARTNER_DB_PATH` (for example `/home/.../private/ledgerline-partners.sqlite`).
3. If the DB stays under `public/api/data/`, keep `public/api/data/.htaccess` deny rules deployed.
4. Confirm HTTPS so the session cookie is marked `Secure`.
5. Optional: set `PARTNER_SESSION_TTL_SECONDS` and rotate/backup the SQLite file with the normal Hostinger backup process.
6. When enabling the deployment portal Partners tab, set the shared admin secret via `PARTNER_ADMIN_TOKEN` **or** Hostinger `private/partner-secrets.php` (same value as `LEDGERLINE_PARTNERS_ADMIN_TOKEN` on Vercel).

No Azure or shared booking API changes are required for partner auth.

## Link to the HighVolt partner service

On signup, the PHP API also sends the partner's application (firm or name, email, country, accepted terms version) server-side to the HighVolt partner service:

`POST {PARTNER_SERVICE_URL}/applications` with `product_key = ledgerline`.

- **Off by default.** Nothing is sent unless `PARTNER_SERVICE_URL` is set, so the live site is unchanged.
- **Best-effort.** If the service is down, website signup still succeeds and the account stays unlinked (`programLinked: false`).
- The returned service partner id is stored in `partners.hva_partner_id`, added automatically to existing databases. It is never returned to the browser.
- Passwords are never sent.
- Stage value: `https://ledgerline-stage.highvolt.tech/platform/v1/partners`. Test against stage only; production needs the partner service live first.

### Live partner data in the portal

`GET /api/partners/program` returns the signed-in partner's real status, referral codes, referral link base and
balance (minor units). `POST /api/partners/program/code` creates their referral code once they are approved.

- This server signs a 60-second RS256 token for the session's own partner only (partner-service ADR-0018) and
  calls `{PARTNER_SERVICE_URL}/site/me/...`. The browser never sees the token or the service partner id, and cannot
  choose another partner.
- Settings:
  - `PARTNER_SITE_SIGNING_KEY`: PEM private key. Env, or `private/partner-secrets.php` outside `public_html`.
    Never in git.
  - `PARTNER_SITE_KEY_ID`: `kid` that matches the public key published in partner-service.
- Without a signing key the portal card stays hidden (`available: false`) and the prototype portal is unchanged.
- Accounts created while the service was down are linked automatically on the next portal visit.
- PHP needs the `openssl` extension. Hostinger has it enabled.
