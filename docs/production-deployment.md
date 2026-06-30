# Production deployment — LedgerLink

Production host: **https://ledgerlink.highvolt.tech**

Preview / staging host: **https://staging.highvolt.tech/ledgerlink**

## Kubernetes

| Environment | Namespace | Config example |
|-------------|-----------|----------------|
| Preview / staging | `quantum-ledgerlink` | [k8s/ledgerlink-config.preview.example.yaml](../k8s/ledgerlink-config.preview.example.yaml) |
| Production | `quantum-ledgerlink-prod` | [k8s/ledgerlink-config.production.example.yaml](../k8s/ledgerlink-config.production.example.yaml) |

Deployment name: `ledgerlink-api` (see existing manifests under `k8s/`).

Staging deployment workflows must continue to use the preview namespace and `/ledgerlink` path prefix. Production uses the apex host without a path prefix.

## Environment variables

### Preview (staging)

```env
APP_ENV=preview
PAYMENT_ENVIRONMENT_LABEL=Preview
STRIPE_MODE=test
PUBLIC_APP_BASE_URL=https://staging.highvolt.tech/ledgerlink
PUBLIC_API_BASE_URL=https://staging.highvolt.tech/ledgerlink/api
STRIPE_GLOBAL_PAYOUTS_ENABLED=false
STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=not_requested
STRIPE_PAYMENTS_EXECUTION_ENABLED=false
STRIPE_LIVE_PAYMENTS_ENABLED=false
```

### Production

```env
APP_ENV=production
PAYMENT_ENVIRONMENT_LABEL=Production
STRIPE_MODE=live
PUBLIC_APP_BASE_URL=https://ledgerlink.highvolt.tech
PUBLIC_API_BASE_URL=https://ledgerlink.highvolt.tech/api
STRIPE_GLOBAL_PAYOUTS_ENABLED=false
STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=not_requested
STRIPE_PAYMENTS_EXECUTION_ENABLED=false
STRIPE_LIVE_PAYMENTS_ENABLED=false
```

Production is deployable with live Stripe keys for **Connect visibility only**. Live payout execution remains disabled until Stripe Global Payouts approval and explicit flags.

## Required production secrets (app-secrets)

Store in Kubernetes secrets or your secret manager — never in ConfigMap or git:

- `DATABASE_URL` or `POSTGRES_*` components
- `JWT_SECRET`
- `STRIPE_SECRET_KEY` (`sk_live_…`)
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CONNECT_CLIENT_ID`
- `STRIPE_GLOBAL_PAYOUTS_WEBHOOK_SECRET` (when Global Payouts webhooks are registered)
- `STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID` (after Stripe onboarding)
- Integration OAuth secrets (Xero, QuickBooks, Microsoft Graph, etc.) as used

## Stripe Global Payouts approval

1. Request **Stripe Global Payouts** for Australia/AUD supplier AP from Stripe.
2. Connect-only remains for account linking, balance, and transaction visibility.
3. Until approval: keep `STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=not_requested` or `pending_approval`.
4. UI shows readiness via `GET /api/payments/stripe/global-payouts/readiness`.
5. Manual payment instruction orchestration remains the default rail.

## Safety flags

| Flag | Production default | Purpose |
|------|-------------------|---------|
| `STRIPE_PAYMENTS_EXECUTION_ENABLED` | `false` | Blocks automated Stripe execution |
| `STRIPE_LIVE_PAYMENTS_ENABLED` | `false` | Blocks live-mode money movement |
| `STRIPE_GLOBAL_PAYOUTS_ENABLED` | `false` | Global Payouts feature gate |
| `PAYMENT_EXECUTION_DISABLED` | `false` | Emergency kill switch |
| `PAYMENT_MANUAL_EXECUTION_ENABLED` | `true` | Manual instruction orchestration |

## Go-live checklist

- [ ] Production database and Redis provisioned
- [ ] `ledgerlink-config` ConfigMap applied for `quantum-ledgerlink-prod`
- [ ] `app-secrets` created with live Stripe **platform** keys (not tenant keys)
- [ ] DNS / TLS for `ledgerlink.highvolt.tech`
- [ ] Stripe Connect OAuth redirect: `https://ledgerlink.highvolt.tech/payments/stripe/oauth/callback`
- [ ] Stripe webhook: `https://ledgerlink.highvolt.tech/api/webhooks/stripe`
- [ ] Migrations applied (`alembic upgrade head`)
- [ ] Payments page shows **Production environment — live payout execution disabled**
- [ ] Global Payouts readiness returns `ready=false` until Stripe approval
- [ ] No code path calls `Transfer.create`, `Payout.create`, or Global Payouts outbound APIs

## Enabling live payouts (future — after Stripe approval)

1. Stripe sets Global Payouts access to enabled on the platform account.
2. Configure financial account and webhook secret.
3. Set `STRIPE_GLOBAL_PAYOUTS_ENABLED=true` and `STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=enabled`.
4. Complete security and business signoff.
5. Set `STRIPE_PAYMENTS_EXECUTION_ENABLED=true` and `STRIPE_LIVE_PAYMENTS_ENABLED=true`.
6. Ship execution implementation in a dedicated release (not included in this foundation).

See [stripe-payments.md](./stripe-payments.md) for API and rail details.
