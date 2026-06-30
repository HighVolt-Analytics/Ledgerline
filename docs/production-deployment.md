# Production deployment — LedgerLink

Production URL: **https://ledgerlink.highvolt.tech** (SPA at root `/`, API at `/api`)

**Legacy manual URL (until root cutover):** https://ledgerlink.highvolt.tech/ledgerlink/login — the production root nginx config redirects `/ledgerlink/*` → `/*` after deploy.

Staging / preview URL: **https://staging.highvolt.tech/ledgerlink** (SPA at `/ledgerlink`, API at `/ledgerlink/api`)

| Database | Environment | Namespace |
|----------|-------------|-----------|
| `ledgerlink_db` | Staging / preview | `quantum-ledgerlink` |
| `ledgerlink_prod` | Production | `quantum-ledgerlink-prod` |

## Kubernetes

| Environment | Namespace | Domain | Config example | Manifests |
|-------------|-----------|--------|----------------|-----------|
| Preview / staging | `quantum-ledgerlink` | `staging.highvolt.tech/ledgerlink` | [k8s/ledgerlink-config.preview.example.yaml](../k8s/ledgerlink-config.preview.example.yaml) | `k8s/*.yaml` |
| Production | `quantum-ledgerlink-prod` | `ledgerlink.highvolt.tech` | [k8s/ledgerlink-config.production.example.yaml](../k8s/ledgerlink-config.production.example.yaml) | `k8s/production/*.yaml` |

Production database name: **`ledgerlink_prod`** (isolated from staging `ledgerlink_db`; CI never clones DBs or overwrites `app-secrets`).

## GitHub Actions

| Workflow | Trigger | Environment |
|----------|---------|-------------|
| [LedgerLink Staging Deploy](../.github/workflows/ledgerlink-staging-deploy.yml) | `develop` push, manual | `ledgerlink-staging` |
| [LedgerLink Production Deploy](../.github/workflows/ledgerlink-production-deploy.yml) | **manual only** (`workflow_dispatch`) | `ledgerlink-production` |

### Required GitHub secrets

Configure in the repository (and/or GitHub Environment **ledgerlink-production**):

| Secret | Used by | Notes |
|--------|---------|-------|
| `AZURE_CREDENTIALS` | Staging + production | Service principal JSON for Azure login |
| `AKS_RESOURCE_GROUP` | Staging + production | AKS resource group name |
| `AKS_CLUSTER_NAME` | Staging + production | AKS cluster name |

The workflows do **not** create or overwrite `app-secrets` (database passwords, JWT, Stripe keys). Provision those manually in each namespace before the first deploy.

### Production deployment steps

1. Create namespace `quantum-ledgerlink-prod` (workflow also ensures it exists).
2. Create `acr-auth` image pull secret and **`app-secrets`** with production values (`POSTGRES_PASSWORD`, `JWT_SECRET`, live Stripe keys, etc.).
3. Apply ConfigMap from the production example (fill non-secret placeholders only):
   ```bash
   kubectl apply -f k8s/ledgerlink-config.production.example.yaml
   ```
4. In GitHub → Actions → **LedgerLink Production Deploy** → Run workflow.
5. Workflow builds:
   - API image: `ledgerlink-api:prod-<sha>` (config from cluster ConfigMap)
   - Frontend image: `ledgerlink-frontend:prod-<sha>` with root SPA (`VITE_BASE_PATH=/`, `VITE_API_BASE=` empty)
6. **Merges** path/URL/safety keys into existing `ledgerlink-config` (does not replace `POSTGRES_HOST`, Redis, or secrets).
7. Applies `k8s/production/*`, rolls out, runs `alembic upgrade head` on **production DB only**, verifies `/health`.

### Smoke tests (after deploy)

```bash
# API health (public — may require auth for some routes)
curl -fsS https://ledgerlink.highvolt.tech/api/payments/stripe/global-payouts/readiness

# Expect JSON envelope; live_execution_enabled=false, ready=false until Stripe approval
```

Browser:

- https://ledgerlink.highvolt.tech/login
- https://ledgerlink.highvolt.tech/payments (shows Production banner, payouts disabled)
- Legacy `/ledgerlink/login` should 301 redirect to `/login`

### Rollback

```bash
# List revisions
kubectl rollout history deployment/ledgerlink-api -n quantum-ledgerlink-prod
kubectl rollout history deployment/ledgerlink-frontend -n quantum-ledgerlink-prod

# Roll back to previous revision
kubectl rollout undo deployment/ledgerlink-api -n quantum-ledgerlink-prod
kubectl rollout undo deployment/ledgerlink-frontend -n quantum-ledgerlink-prod

# Or pin a known-good image tag
kubectl set image deployment/ledgerlink-frontend \
  ledgerlink-frontend=highvoltacr1778087855.azurecr.io/ledgerlink-frontend:prod-<sha> \
  -n quantum-ledgerlink-prod
```

Migrations are forward-only in CI; roll back application images first. If a migration must be reversed, run a targeted Alembic downgrade manually after review.

## Environment variables

### Preview (staging)

```env
APP_ENV=preview
ENVIRONMENT=preview
PAYMENT_ENVIRONMENT_LABEL=Preview
BASE_PATH=/ledgerlink
API_BASE_PATH=/ledgerlink/api
PUBLIC_APP_BASE_URL=https://staging.highvolt.tech/ledgerlink
PUBLIC_API_BASE_URL=https://staging.highvolt.tech/ledgerlink/api
POSTGRES_DB=ledgerlink_db
STRIPE_MODE=test
STRIPE_GLOBAL_PAYOUTS_ENABLED=false
STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=not_requested
STRIPE_PAYMENTS_EXECUTION_ENABLED=false
STRIPE_LIVE_PAYMENTS_ENABLED=false
```

Frontend build (staging workflow): `VITE_BASE_PATH=/ledgerlink/`, `VITE_API_BASE=/ledgerlink`

### Production

```env
APP_ENV=production
ENVIRONMENT=production
PAYMENT_ENVIRONMENT_LABEL=Production
BASE_PATH=/
API_BASE_PATH=/api
PUBLIC_APP_BASE_URL=https://ledgerlink.highvolt.tech
PUBLIC_API_BASE_URL=https://ledgerlink.highvolt.tech/api
CORS_ORIGINS=https://ledgerlink.highvolt.tech
POSTGRES_DB=ledgerlink_prod
STRIPE_MODE=live
STRIPE_GLOBAL_PAYOUTS_ENABLED=false
STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=not_requested
STRIPE_PAYMENTS_EXECUTION_ENABLED=false
STRIPE_LIVE_PAYMENTS_ENABLED=false
```

Frontend build (production workflow): `VITE_BASE_PATH=/`, `VITE_API_BASE=` (empty → API calls use `/api/...`)

Production is deployable with live Stripe keys for **Connect visibility only**. Live payout execution remains disabled until Stripe Global Payouts approval and explicit flags.

## Required production secrets (`app-secrets`)

Store in Kubernetes secrets or your secret manager — never in ConfigMap or git:

- `POSTGRES_PASSWORD` (or full `DATABASE_URL`) for **`ledgerlink_prod`**
- `JWT_SECRET`
- `STRIPE_SECRET_KEY` (`sk_live_…`)
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CONNECT_CLIENT_ID`
- `STRIPE_GLOBAL_PAYOUTS_WEBHOOK_SECRET` (when Global Payouts webhooks are registered)
- `STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID` (after Stripe onboarding)
- Integration OAuth secrets (Xero, QuickBooks, Microsoft Graph, etc.) as used

## Stripe Global Payouts approval (pending)

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

- [ ] Production database `ledgerlink_prod` and Redis provisioned
- [ ] `ledgerlink-config` ConfigMap applied for `quantum-ledgerlink-prod`
- [ ] `app-secrets` created with live Stripe **platform** keys (not tenant keys)
- [ ] DNS / TLS for `ledgerlink.highvolt.tech`
- [ ] Azure Front Door routes apex host to production LoadBalancer origins (root `/`, not `/ledgerlink`)
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
