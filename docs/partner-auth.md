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

If `PARTNER_ADMIN_TOKEN` is unset on the Ledgerline host, the endpoint fails closed with `401`.

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
- `PARTNER_ADMIN_TOKEN` — shared secret for `GET /api/partners/admin/list` (required for portal Partners tab)
- `PHP_BIN` — PHP executable for Vite/tests
- `PHP_EXTENSION_DIR` — override extension directory when enabling `pdo_sqlite` locally

## Connecting the HighVolt deployment portal

Do **not** change production from this PR. To wire the portal Partners tab after both PRs are ready:

| Where | Variable | Purpose |
|---|---|---|
| Ledgerline (Hostinger PHP) | `PARTNER_ADMIN_TOKEN` | Shared secret that authorizes the admin list |
| Deploy portal (Vercel) | `LEDGERLINE_PARTNERS_API_BASE` | Origin only, e.g. `https://www.quantumledgerline.com` (no path) |
| Deploy portal (Vercel) | `LEDGERLINE_PARTNERS_ADMIN_TOKEN` | Same value as `PARTNER_ADMIN_TOKEN` |

The portal BFF calls `{LEDGERLINE_PARTNERS_API_BASE}/api/partners/admin/list` with the Bearer token. The browser never receives the token or the SQLite path.

## Production configuration still needed

Do **not** change these from this PR. Before enabling partner auth in production:

1. **PHP** enabled for `quantumledgerline.com` document root (Hostinger).
2. **Writable data directory** for SQLite, preferably outside the web root, via `PARTNER_DB_PATH` (for example `/home/.../private/ledgerline-partners.sqlite`).
3. If the DB stays under `public/api/data/`, keep `public/api/data/.htaccess` deny rules deployed.
4. Confirm HTTPS so the session cookie is marked `Secure`.
5. Optional: set `PARTNER_SESSION_TTL_SECONDS` and rotate/backup the SQLite file with the normal Hostinger backup process.
6. Set `PARTNER_ADMIN_TOKEN` only when enabling the deployment portal Partners tab (same secret as `LEDGERLINE_PARTNERS_ADMIN_TOKEN` on Vercel).

No Azure or shared booking API changes are required for partner auth.
