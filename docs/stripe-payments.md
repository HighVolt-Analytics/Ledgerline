# Stripe Payments - Connect sandbox setup

LedgerLink disbursement uses **Stripe Connect**. This guide covers architecture, sandbox configuration, webhooks, readiness validation, and production gates.

Related: [azure-env-mapping.md](./azure-env-mapping.md) - template: [backend/.env.example](../backend/.env.example) - K8s: [k8s/ledgerlink-config.example.yaml](../k8s/ledgerlink-config.example.yaml)

## Architecture

- **LedgerLink uses Stripe Connect** - tenant organisations onboard as Stripe **connected accounts** (Express) or connect an existing **Standard** account via OAuth.
- **LedgerLink is the Stripe platform** - the platform Stripe account owns Connect, webhooks, and API calls. Tenants never become the platform.
- **Users must never paste Stripe secret keys into LedgerLink** - no UI fields for `sk_*`, `whsec_*`, or Connect client secrets. Operators configure secrets only via environment variables, Kubernetes `app-secrets`, or GitHub Actions secrets.
- **Persisted data is metadata only** - Stripe account IDs, onboarding/charges/payouts flags, balance snapshots, balance transactions, payment attempt references, and webhook `stripe_event_id` dedupe rows. No card numbers, bank account numbers, or raw webhook secrets in the database.

Internal payables workflow (queue -> approval -> scheduled) remains separate from Stripe money movement until explicitly enabled in a later phase.

## Implemented (staging)

| Feature | Status |
|---------|--------|
| Connect onboarding (Account Links) | Complete |
| OAuth existing Standard account | Complete |
| Disconnect / reconnect | Complete |
| Balance and transactions (read-only) | Complete |
| Stripe readiness guards | Complete |
| Vendor payout method readiness | Complete |
| Deterministic payment-to-vendor linking (`vendor_registry_id`) | Complete |
| Payment execution dry-run validation | Complete |
| Single payment approval (logged-in approver → scheduled) | Complete |

**Real transfers, payouts, PaymentIntents, top-ups, withdrawals, and external supplier bank payouts are not enabled.** The Payments UI supports **readiness validation only** unless production safety flags are explicitly approved and execution endpoints are implemented in a future release.

### Payment approval (readiness only)

- Payments move **Queue → Awaiting approval → Scheduled** via the Payments page.
- **Approve payment** binds approval to the logged-in user (`POST /api/payments/{id}/approve`).
- **Validate payment** runs a dry-run readiness check; after approval, Stripe setup blocks may remain until Connect onboarding is complete.
- **Pay Now** and real execution remain disabled unless `STRIPE_PAYMENTS_EXECUTION_ENABLED` is explicitly approved for a future release.

## Sandbox setup

### Required secret environment variables

Store in `backend/.env` locally, Kubernetes **`app-secrets`**, or the **`ledgerlink-staging`** GitHub environment - never commit real values.

| Variable | Description |
|----------|-------------|
| `STRIPE_SECRET_KEY` | Platform secret key (`sk_test_...` in sandbox) |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for the staging webhook endpoint (`whsec_...`) |
| `STRIPE_CONNECT_CLIENT_ID` | Connect OAuth client ID (`ca_...`); required to connect an existing Stripe Standard account via OAuth |

### Required non-secret environment variables

| Variable | Staging example |
|----------|-----------------|
| `STRIPE_MODE` | `sandbox` |
| `STRIPE_RETURN_URL` | `https://staging.highvolt.tech/ledgerlink/payments` |
| `STRIPE_REFRESH_URL` | `https://staging.highvolt.tech/ledgerlink/payments` |
| `STRIPE_OAUTH_REDIRECT_URL` | `https://staging.highvolt.tech/ledgerlink/payments/stripe/oauth/callback` |
| `STRIPE_PAYMENTS_EXECUTION_ENABLED` | `false` (default) |
| `STRIPE_LIVE_PAYMENTS_ENABLED` | `false` (default) |

`STRIPE_RETURN_URL` and `STRIPE_REFRESH_URL` are used by the Express Account Links onboarding flow. `STRIPE_OAUTH_REDIRECT_URL` is the OAuth redirect URI for connecting an **existing** Stripe Standard account; it must be registered exactly in **Stripe Dashboard -> Connect -> OAuth settings** (redirect URIs allowlist).

Local dev (Vite on port 5173):

```env
STRIPE_MODE=sandbox
STRIPE_RETURN_URL=http://localhost:5173/payments
STRIPE_REFRESH_URL=http://localhost:5173/payments
STRIPE_OAUTH_REDIRECT_URL=http://localhost:5173/payments/stripe/oauth/callback
STRIPE_PAYMENTS_EXECUTION_ENABLED=false
STRIPE_LIVE_PAYMENTS_ENABLED=false
```

Apply migrations **038–040** before testing:

```powershell
cd backend
alembic upgrade head
```

### Stripe Dashboard (sandbox)

1. Enable **Connect** on the platform account (test mode).
2. Create a **Connect** settings profile; note the **client ID** for `STRIPE_CONNECT_CLIENT_ID` (required for OAuth existing-account connection).
3. Under **Connect -> OAuth settings**, add `STRIPE_OAUTH_REDIRECT_URL` to the **redirect URIs** allowlist (must match exactly, including path and scheme).
4. Under **Developers -> API keys**, use the **test** secret key for `STRIPE_SECRET_KEY`.
5. In the LedgerLink UI (**Payments**), click **Connect Stripe** or **Connect existing Stripe account** to link a test connected account.

### Connect paths

| Path | Flow | Key configuration |
|------|------|-------------------|
| New Express account | Account Links onboarding | `STRIPE_RETURN_URL`, `STRIPE_REFRESH_URL` |
| Existing Standard account | Connect OAuth | `STRIPE_CONNECT_CLIENT_ID`, `STRIPE_OAUTH_REDIRECT_URL` |

## Payment execution dry-run validation

Use **Validate payment** on the Payments page (or `POST /api/payments/{payment_id}/execution-readiness`) to check whether a payment would be executable **without moving money**.

The dry-run checks:

- Payment exists and is not already paid/failed
- Positive amount and supported currency (AUD)
- Approval workflow complete (scheduled with all approvers approved)
- Tenant Stripe connected with `charges_enabled` and `payouts_enabled`
- Payment linked to vendor registry (FK or name fallback with warning)
- Vendor default payout method verified and of a supported type

Response includes `can_execute`, `blocking_reasons`, `warnings`, and `recommended_action`. Dry-run runs while `STRIPE_PAYMENTS_EXECUTION_ENABLED=false`.

Audit event: `payment_execution_readiness_validated`.

## Webhook endpoint

| Environment | URL |
|-------------|-----|
| Staging | `https://staging.highvolt.tech/ledgerlink/api/webhooks/stripe` |

- The route is **public** (no JWT) but **requires Stripe signature verification** via the `Stripe-Signature` header and `STRIPE_WEBHOOK_SECRET`.
- Handlers **record events once** - duplicate deliveries with the same `stripe_event_id` are detected via a unique constraint on `stripe_webhook_events` and return `{"received": true, "duplicate": true}` without reprocessing.
- `account.updated` syncs connected-account readiness flags into LedgerLink.
- Payment state mutation from payment-intent webhooks is not enabled yet.

Configure the endpoint in **Stripe Dashboard -> Developers -> Webhooks** (test mode), then copy the signing secret into `STRIPE_WEBHOOK_SECRET`.

## Audit events (Stripe / payments)

Logged via `audit_service.log_event` (visible on dashboard activity feed):

| Event | When |
|-------|------|
| `stripe_account_connected_onboarding` | Express Account Links connect |
| `stripe_account_connected_oauth` | OAuth existing-account connect |
| `stripe_account_disconnected` | Tenant disconnects Stripe |
| `stripe_status_refreshed` | Manual Stripe status refresh |
| `vendor_payout_method_created` | Vendor payout method added |
| `vendor_payout_method_updated` | Vendor payout method updated |
| `vendor_payout_method_deleted` | Vendor payout method removed |
| `payment_execution_readiness_validated` | Dry-run validation requested |
| `payment_approved` | Payment approved by logged-in user (awaiting → scheduled) |

## Production safety

**Do not enable live Stripe money movement on production** (`https://ai.highvolt.tech/ledgerlink`) until all of the following are complete:

- [ ] UAT signoff on staging (`staging.highvolt.tech/ledgerlink`)
- [ ] Stripe sandbox validation (Connect onboarding, OAuth, balance, transactions, webhooks, dry-run)
- [ ] Internal payment approval workflow validation (queue / tiers / status transitions)
- [ ] Security review (secrets handling, webhook verification, tenant isolation / RLS)
- [ ] Business signoff recorded

### Production cutover checklist

- [ ] Live Stripe platform account activated
- [ ] Live webhook endpoint configured and `STRIPE_WEBHOOK_SECRET` rotated in production `app-secrets`
- [ ] Live Connect OAuth redirect URI registered and `STRIPE_OAUTH_REDIRECT_URL` set to production host
- [ ] AKS secrets patched with live `STRIPE_SECRET_KEY` and `STRIPE_CONNECT_CLIENT_ID`
- [ ] `STRIPE_MODE=live` (or equivalent) and return/refresh URLs point to production host
- [ ] Safety flags explicitly approved: `STRIPE_PAYMENTS_EXECUTION_ENABLED`, `STRIPE_LIVE_PAYMENTS_ENABLED`
- [ ] Dry-run validation passed for representative payments
- [ ] Business signoff recorded before enabling real execution endpoints (future phase)

Use **live** keys (`sk_live_...`, live webhook secret, live Connect client ID) only after the above gates.

## Phase 2 - external supplier bank payouts

- **External supplier bank payouts** (vendor bank accounts, Connect transfers to third parties) are **Phase 2**, pending Stripe eligibility and compliance review.
- Vendor payout method type `external_bank_phase2` is stored for planning but **blocked** in dry-run validation.
- **Top Up** and **Withdraw** in the Payments UI remain **disabled** until backend support is implemented and approved.
- The internal payables queue and manual status workflow continue to operate without moving real funds through Stripe.

## API surface (reference)

Authenticated (payments module, JWT):

| Method | Path |
|--------|------|
| GET | `/api/payments` |
| PATCH | `/api/payments/{payment_id}` |
| POST | `/api/payments/{payment_id}/approve` |
| POST | `/api/payments/{payment_id}/execution-readiness` |
| GET | `/api/payments/stripe/account` |
| POST | `/api/payments/stripe/account/refresh` |
| DELETE | `/api/payments/stripe/account` |
| POST | `/api/payments/stripe/connect` |
| GET | `/api/payments/stripe/onboarding-link` |
| GET | `/api/payments/stripe/oauth-url` |
| GET | `/api/payments/stripe/readiness` |
| GET | `/api/payments/stripe/balance` |
| GET | `/api/payments/stripe/transactions` |

Vendor payout methods (JWT):

| Method | Path |
|--------|------|
| GET/POST | `/api/vendors/{vendor_id}/payout-methods` |
| PATCH/DELETE | `/api/vendors/{vendor_id}/payout-methods/{method_id}` |

Public:

| Method | Path |
|--------|------|
| POST | `/api/webhooks/stripe` |
