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

Passwords are stored only as `password_hash()` digests. Sessions use an HttpOnly cookie (`ll_partner_session`). Passwords are never written to `localStorage`.

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
- `PHP_BIN` — PHP executable for Vite/tests
- `PHP_EXTENSION_DIR` — override extension directory when enabling `pdo_sqlite` locally

## Production configuration still needed

Do **not** change these from this PR. Before enabling partner auth in production:

1. **PHP** enabled for `quantumledgerline.com` document root (Hostinger).
2. **Writable data directory** for SQLite, preferably outside the web root, via `PARTNER_DB_PATH` (for example `/home/.../private/ledgerline-partners.sqlite`).
3. If the DB stays under `public/api/data/`, keep `public/api/data/.htaccess` deny rules deployed.
4. Confirm HTTPS so the session cookie is marked `Secure`.
5. Optional: set `PARTNER_SESSION_TTL_SECONDS` and rotate/backup the SQLite file with the normal Hostinger backup process.

No Azure or shared booking API changes are required for partner auth.
