# Stripe Payments - Connect sandbox setup

LedgerLink disbursement uses **Stripe Connect**. This guide covers architecture, sandbox configuration, webhooks, and production gates.

Related: [azure-env-mapping.md](./azure-env-mapping.md) - template: [backend/.env.example](../backend/.env.example) - K8s: [k8s/ledgerlink-config.example.yaml](../k8s/ledgerlink-config.example.yaml)

## Architecture

- **LedgerLink uses Stripe Connect** - tenant organisations onboard as Stripe **connected accounts** (Express).
- **LedgerLink is the Stripe platform** - the platform Stripe account owns Connect, webhooks, and API calls. Tenants never become the platform.
- **Users must never paste Stripe secret keys into LedgerLink** - no UI fields for `sk_*`, `whsec_*`, or Connect client secrets. Operators configure secrets only via environment variables, Kubernetes `app-secrets`, or GitHub Actions secrets.
- **Persisted data is metadata only** - Stripe account IDs, onboarding/charges/payouts flags, balance snapshots, balance transactions, payment attempt references, and webhook `stripe_event_id` dedupe rows. No card numbers, bank account numbers, or raw webhook secrets in the database.

Internal payables workflow (queue -> approval -> scheduled) remains separate from Stripe money movement until explicitly enabled in a later phase.

## Sandbox setup

### Required secret environment variables

Store in `backend/.env` locally, Kubernetes **`app-secrets`**, or the **`ledgerlink-staging`** GitHub environment - never commit real values.

| Variable | Description |
|----------|-------------|
| `STRIPE_SECRET_KEY` | Platform secret key (`sk_test_...` in sandbox) |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for the staging webhook endpoint (`whsec_...`) |
| `STRIPE_CONNECT_CLIENT_ID` | Connect OAuth client ID (`ca_...`) |

### Required non-secret environment variables

| Variable | Staging example |
|----------|-----------------|
| `STRIPE_MODE` | `sandbox` |
| `STRIPE_RETURN_URL` | `https://staging.highvolt.tech/ledgerlink/payments` |
| `STRIPE_REFRESH_URL` | `https://staging.highvolt.tech/ledgerlink/payments` |

Local dev (Vite on port 5173):

```env
STRIPE_MODE=sandbox
STRIPE_RETURN_URL=http://localhost:5173/payments
STRIPE_REFRESH_URL=http://localhost:5173/payments
```

Apply migration **038** (`stripe_accounts`, webhook dedupe, etc.) before testing:

```powershell
cd backend
alembic upgrade head
```

### Stripe Dashboard (sandbox)

1. Enable **Connect** on the platform account (test mode).
2. Create a **Connect** settings profile; note the **client ID** for `STRIPE_CONNECT_CLIENT_ID`.
3. Under **Developers -> API keys**, use the **test** secret key for `STRIPE_SECRET_KEY`.
4. In the LedgerLink UI (**Payments**), click **Connect Stripe** or **Continue onboarding** to complete Express onboarding for a test connected account.

## Webhook endpoint

| Environment | URL |
|-------------|-----|
| Staging | `https://staging.highvolt.tech/ledgerlink/api/webhooks/stripe` |

- The route is **public** (no JWT) but **requires Stripe signature verification** via the `Stripe-Signature` header and `STRIPE_WEBHOOK_SECRET`.
- Handlers **record events once** - duplicate deliveries with the same `stripe_event_id` are detected via a unique constraint on `stripe_webhook_events` and return `{"received": true, "duplicate": true}` without reprocessing.
- Payment state mutation from webhooks is not enabled yet; events are stored for audit and future processing.

Configure the endpoint in **Stripe Dashboard -> Developers -> Webhooks** (test mode), then copy the signing secret into `STRIPE_WEBHOOK_SECRET`.

## Production safety

**Do not enable Stripe Payments on production** (`https://ai.highvolt.tech/ledgerlink`) until all of the following are complete:

- [ ] UAT signoff on staging (`staging.highvolt.tech/ledgerlink`)
- [ ] Stripe sandbox validation (Connect onboarding, balance, transactions, webhooks)
- [ ] Internal payment approval workflow validation (queue / tiers / status transitions)
- [ ] Security review (secrets handling, webhook verification, tenant isolation / RLS)
- [ ] Production Stripe keys approved and rotated into production `app-secrets` only

Use **live** keys (`sk_live_...`, live webhook secret, live Connect client ID) only after the above gates. Set `STRIPE_MODE` and return/refresh URLs to the production host when going live.

## Phase 2 - external supplier bank payouts

- **External supplier bank payouts** (vendor bank accounts, Connect transfers to third parties) are **Phase 2**, pending Stripe eligibility and compliance review.
- **Top Up** and **Withdraw** in the Payments UI remain **disabled** until backend support is implemented and approved.
- The internal payables queue and manual status workflow continue to operate without moving real funds through Stripe.

## API surface (reference)

Authenticated (payments module, JWT):

| Method | Path |
|--------|------|
| GET | `/api/payments/stripe/account` |
| POST | `/api/payments/stripe/connect` |
| GET | `/api/payments/stripe/onboarding-link` |
| GET | `/api/payments/stripe/balance` |
| GET | `/api/payments/stripe/transactions` |

Public:

| Method | Path |
|--------|------|
| POST | `/api/webhooks/stripe` |
