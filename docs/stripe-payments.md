# Stripe Payments - Connect sandbox setup

LedgerLink disbursement uses **Stripe Connect**. This guide covers architecture, sandbox configuration, webhooks, readiness validation, and production gates.

Related: [azure-env-mapping.md](./azure-env-mapping.md) - template: [backend/.env.example](../backend/.env.example) - K8s: [k8s/ledgerlink-config.example.yaml](../k8s/ledgerlink-config.example.yaml)

## Architecture

- **LedgerLink uses Stripe Connect** - tenant organisations onboard as Stripe **connected accounts** (Express) or connect an existing **Standard** account via OAuth.
- **LedgerLink is the Stripe platform** - the platform Stripe account owns Connect, webhooks, and API calls. Tenants never become the platform.
- **Users must never paste Stripe secret keys into LedgerLink** - no UI fields for `sk_*`, `whsec_*`, or Connect client secrets. Operators configure secrets only via environment variables, Kubernetes `app-secrets`, or GitHub Actions secrets.
- **Persisted data is metadata only** - Stripe account IDs, onboarding/charges/payouts flags, balance snapshots, balance transactions, payment attempt references, and webhook `stripe_event_id` dedupe rows. No card numbers, bank account numbers, or raw webhook secrets in the database.

Internal payables workflow (queue -> approval -> scheduled) remains separate from Stripe money movement until explicitly enabled in a later phase.

# Production manual payment execution controls

LedgerLink production disbursement uses **client-controlled manual execution**. The client/tenant pays suppliers from their own bank or wallet. LedgerLink creates payment instructions and records completion. **LedgerLink does not custody client funds.**

## Production model (signoff received)

| Control | Production value |
|---------|------------------|
| Payment rail | Client manual bank/wallet payment outside LedgerLink |
| Funds ownership | Client/tenant owns funds; LedgerLink orchestrates only |
| Execution roles | Tenant Admin (`admin`) or Approver (`approver`) |
| Approval | Single approver at launch |
| Per-payment limit | USD 1000 (`PAYMENT_MANUAL_EXECUTION_LIMIT_USD`) |
| Vendor requirement | Verified default payout method before instruction |
| Stripe money APIs | Transfer/Payout/PaymentIntent execution **disabled** |
| Stripe Connect | Account connection, readiness, balance visibility only |
| Emergency disable | Global `PAYMENT_EXECUTION_DISABLED` or per-tenant `settings_json.payment_execution_disabled` |

### Manual paid confirmation requires

- Payment/bank **reference** number
- **Proof/reference** (`proof_reference` text; file attachment integration planned)
- **Paid date**

Mark paid is accounting status only — **no funds are moved**.

## Implemented (staging / production-safe)

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
| Manual payment instruction orchestration (`manual_instruction`) | Complete |
| Manual paid confirmation (accounting status only) | Complete |

**Real transfers, payouts, PaymentIntents, top-ups, withdrawals, and external supplier bank payouts are not enabled.** LedgerLink orchestrates payment instructions and records manual completion; it does **not** custody client funds or move money through Stripe in this release.

### Payment approval and manual execution

- Payments move **Queue → Awaiting approval → Scheduled** via the Payments page.
- **Approve payment** binds approval to the logged-in user (`POST /api/payments/{id}/approve`).
- **Validate payment** runs a dry-run readiness check; after approval, Stripe setup may still block automated rails until Connect onboarding is complete.
- **Create payment instruction** (`POST /api/payments/{id}/execution-instruction`) generates a read-only manual instruction when `PAYMENT_MANUAL_EXECUTION_ENABLED=true`. No funds are moved.
- **Mark paid manually** (`POST /api/payments/{id}/mark-paid-manual`) records paid status with a client-supplied bank reference. Accounting status only — no funds are moved.
- **Pay Now** and real Stripe execution remain disabled unless `STRIPE_PAYMENTS_EXECUTION_ENABLED` is explicitly approved for a future release with implemented money-movement endpoints.

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
| `PAYMENT_MANUAL_EXECUTION_ENABLED` | `false` (default); set `true` on staging for manual instruction dry-run |
| `PAYMENT_MANUAL_EXECUTION_LIMIT_USD` | `1000` (launch cap per payment; non-USD uses same numeric threshold without FX) |
| `PAYMENT_EXECUTION_DISABLED` | `false` (global emergency kill switch) |
| Per-tenant disable | `tenants.settings_json.payment_execution_disabled=true` |

`STRIPE_RETURN_URL` and `STRIPE_REFRESH_URL` are used by the Express Account Links onboarding flow. `STRIPE_OAUTH_REDIRECT_URL` is the OAuth redirect URI for connecting an **existing** Stripe Standard account; it must be registered exactly in **Stripe Dashboard -> Connect -> OAuth settings** (redirect URIs allowlist).

Local dev (Vite on port 5173):

```env
STRIPE_MODE=sandbox
STRIPE_RETURN_URL=http://localhost:5173/payments
STRIPE_REFRESH_URL=http://localhost:5173/payments
STRIPE_OAUTH_REDIRECT_URL=http://localhost:5173/payments/stripe/oauth/callback
STRIPE_PAYMENTS_EXECUTION_ENABLED=false
STRIPE_LIVE_PAYMENTS_ENABLED=false
PAYMENT_MANUAL_EXECUTION_ENABLED=false
PAYMENT_MANUAL_EXECUTION_LIMIT_USD=1000
PAYMENT_EXECUTION_DISABLED=false
```

Apply migrations **038–042** before testing:

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

## Manual payment instruction orchestration

When `PAYMENT_MANUAL_EXECUTION_ENABLED=true` (and `PAYMENT_EXECUTION_DISABLED=false`), scheduled payments can receive a **manual instruction** without Stripe money APIs.

### Create instruction

`POST /api/payments/{payment_id}/execution-instruction`

- Payment must be **scheduled** with approval complete.
- Runs dry-run validation first (read-only).
- If Stripe payout rails are blocked, manual instruction is still allowed when the vendor default payout method is `manual_bank` and **verified**.
- Creates `payment_execution_instructions` row with `execution_mode=manual_instruction`, `status=instruction_created`.
- Idempotent: returns existing instruction if already created.
- Does **not** mark paid or move funds.

### Mark paid manually

`POST /api/payments/{payment_id}/mark-paid-manual`

Body: `{ "reference": "BANK-TXN-123", "paid_date": "2026-06-26", "proof_reference": "receipt-scan-ref", "note": "optional" }`

- Allowed when payment is **scheduled** with an active instruction.
- Requires Tenant Admin or Approver role.
- Sets `status=paid`, stores reference on `payment_intent`, proof on instruction row.
- Accounting status only — **no money movement**.
- File attachment upload for proof is planned; `proof_reference` text is required for now.

### Export instruction

`GET /api/payments/{payment_id}/execution-instruction/export`

Returns JSON with instruction fields for copy/export in the UI.

### Safety gates

| Flag | Effect |
|------|--------|
| `PAYMENT_EXECUTION_DISABLED=true` | Blocks instruction and mark-paid endpoints |
| `PAYMENT_MANUAL_EXECUTION_ENABLED=false` | Blocks manual orchestration (default) |
| `PAYMENT_MANUAL_EXECUTION_LIMIT_USD` | Rejects instructions above USD 1000 launch limit |
| Per-tenant `payment_execution_disabled` | Blocks instruction and mark-paid for that tenant |
| Role | Tenant Admin or Approver required for approve/instruction/mark-paid |
| `STRIPE_PAYMENTS_EXECUTION_ENABLED` | Reserved for future real Stripe rails only; manual orchestration does not call Stripe money APIs |

Staging example (manual instruction only, no real payouts):

```env
STRIPE_PAYMENTS_EXECUTION_ENABLED=false
STRIPE_LIVE_PAYMENTS_ENABLED=false
PAYMENT_MANUAL_EXECUTION_ENABLED=true
PAYMENT_MANUAL_EXECUTION_LIMIT_USD=1000
PAYMENT_EXECUTION_DISABLED=false
```

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
| `payment_execution_instruction_created` | Manual payment instruction created |
| `payment_marked_paid_manual` | Payment marked paid manually (no funds moved) |
| `payment_execution_blocked_by_safety_gate` | Global safety flag blocked execution |
| `payment_execution_blocked_by_tenant_disable` | Tenant payment execution disabled |
| `payment_execution_blocked_by_limit` | Payment exceeds USD 1000 launch limit |

## Production safety

**Do not enable live Stripe money movement on production** (`https://ai.highvolt.tech/ledgerlink`) until all of the following are complete:

- [ ] UAT signoff on staging (`staging.highvolt.tech/ledgerlink`)
- [ ] Stripe sandbox validation (Connect onboarding, OAuth, balance, transactions, webhooks, dry-run)
- [ ] Internal payment approval workflow validation (queue / tiers / status transitions)
- [ ] Manual instruction and mark-paid workflow validated on staging
- [ ] Security review (secrets handling, webhook verification, tenant isolation / RLS)
- [ ] Business / legal / compliance signoff for the chosen payout rail

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
| POST | `/api/payments/{payment_id}/execution-instruction` |
| GET | `/api/payments/{payment_id}/execution-instruction/export` |
| POST | `/api/payments/{payment_id}/mark-paid-manual` |
| GET | `/api/payments/stripe/account` |
| POST | `/api/payments/stripe/account/refresh` |
| DELETE | `/api/payments/stripe/account` |
| POST | `/api/payments/stripe/connect` |
| GET | `/api/payments/stripe/onboarding-link` |
| GET | `/api/payments/stripe/oauth-url` |
| GET | `/api/payments/stripe/readiness` |
| GET | `/api/payments/stripe/global-payouts/readiness` |
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
| POST | `/api/webhooks/stripe/global-payouts` |

## Stripe Global Payouts (Australia / AUD supplier AP)

Stripe confirmed **Connect-only is not sufficient** for Australia/AUD accounts-payable supplier payments. LedgerLink prepares for **Stripe Global Payouts** while keeping all outbound money APIs disabled until Stripe approval and explicit configuration.

### URLs

| Environment | App URL | API base |
|-------------|---------|----------|
| Preview / staging | https://staging.highvolt.tech/ledgerlink | https://staging.highvolt.tech/ledgerlink/api |
| Production | https://ledgerlink.highvolt.tech | https://ledgerlink.highvolt.tech/api |

### Configuration (no secrets in UI)

| Variable | Purpose |
|----------|---------|
| `APP_ENV` | `preview` or `production` |
| `PAYMENT_ENVIRONMENT_LABEL` | Display label (`Preview` / `Production`) |
| `PUBLIC_APP_BASE_URL` | Public app origin |
| `PUBLIC_API_BASE_URL` | Public API origin |
| `STRIPE_MODE` | `test` (preview) or `live` (production) |
| `STRIPE_GLOBAL_PAYOUTS_ENABLED` | Feature flag (default `false`) |
| `STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS` | `not_requested` \| `pending_approval` \| `enabled` \| `rejected` |
| `STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID` | Stripe financial account id (secret store) |
| `STRIPE_GLOBAL_PAYOUTS_WEBHOOK_SECRET` | Webhook signing secret (secret store) |
| `STRIPE_GLOBAL_PAYOUTS_MAX_AMOUNT_USD` | Launch limit (default 1000) |
| `STRIPE_GLOBAL_PAYOUTS_SUPPORTED_COUNTRIES` | e.g. `AU` |
| `STRIPE_GLOBAL_PAYOUTS_SUPPORTED_CURRENCIES` | e.g. `AUD,USD` |

Existing safety flags (unchanged):

- `STRIPE_PAYMENTS_EXECUTION_ENABLED=false`
- `STRIPE_LIVE_PAYMENTS_ENABLED=false`

`live_execution_enabled` is true only when Global Payouts readiness is true **and** both execution flags are true.

### Payment rails

| Rail | Status |
|------|--------|
| `manual_instruction` | **Default** — production manual orchestration |
| `stripe_global_payouts` | Selected when Global Payouts readiness is true (execution APIs not implemented) |
| `stripe_treasury` | Placeholder |
| `external_ap_provider` | Placeholder |

Dry-run readiness (`POST /api/payments/{id}/execution-readiness`) includes rail metadata: `selected_payment_rail`, `stripe_global_payouts_ready`, `payment_rail_ready`, `app_env`, `stripe_mode`, `live_execution_enabled`.

### Webhooks (placeholder)

`POST /api/webhooks/stripe/global-payouts` verifies `STRIPE_GLOBAL_PAYOUTS_WEBHOOK_SECRET` when configured, records event id/type, and does **not** mutate payments yet.

Expected future event types:

- `v2.money_management.outbound_payment.created`
- `v2.money_management.outbound_payment.posted`
- `v2.money_management.outbound_payment.failed`
- `v2.money_management.outbound_payment.returned`
- `v2.money_management.payout_method.created`

### Go-live checklist (after Stripe approval)

1. Stripe enables Global Payouts on the platform account.
2. Set `STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=enabled` and configure financial account id.
3. Register production webhook URL: `https://ledgerlink.highvolt.tech/api/webhooks/stripe/global-payouts`
4. Complete UAT on preview with `STRIPE_MODE=test`.
5. Deploy production ConfigMap (`k8s/ledgerlink-config.production.example.yaml`) with `STRIPE_MODE=live`.
6. Only after business/security signoff: set `STRIPE_PAYMENTS_EXECUTION_ENABLED=true` and `STRIPE_LIVE_PAYMENTS_ENABLED=true`.
7. Implement outbound payment API integration in a follow-up release (not in this foundation).

**No-money-movement rule:** LedgerLink must not call `Transfer.create`, `Payout.create`, Global Payouts outbound payment APIs, or Treasury outbound APIs until steps above are complete and execution code is explicitly implemented.

See also: [production-deployment.md](./production-deployment.md)
