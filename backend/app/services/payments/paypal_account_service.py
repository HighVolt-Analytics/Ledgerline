"""PayPal tenant account connect / callback / readiness / disconnect."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant_payment_provider import (
    PROVIDER_PAYPAL,
    TenantPaymentProviderAccount,
)
from app.services.audit.audit_service import log_event
from app.services.integration.xero.xero_token_service import (
    STATE_TTL_SECONDS,
    consume_oauth_jti,
)
from app.services.payments.paypal_client import PaypalApiError, get_paypal_client
from app.services.shared.token_vault import encrypt_secret
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATE_TYP = "paypal_connect_oauth"
STATE_TTL_MINUTES = 20
STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTED = "connected"
STATUS_PENDING = "pending"
ONBOARDING_COMPLETE = "complete"
ONBOARDING_PENDING = "pending"
ONBOARDING_SANDBOX_TEST = "sandbox_test"


class PaypalAccountError(Exception):
    """Safe application error for PayPal account operations."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def create_oauth_state(*, tenant_id: uuid.UUID | str, user_id: int) -> str:
    org_id = parse_tenant_id(tenant_id)
    if org_id is None:
        raise PaypalAccountError("Invalid tenant id")
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": STATE_TYP,
        "provider": PROVIDER_PAYPAL,
        "org_id": str(org_id),
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "exp": expire,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != STATE_TYP:
        raise PaypalAccountError("Invalid OAuth state")
    if payload.get("provider") != PROVIDER_PAYPAL:
        raise PaypalAccountError("OAuth state provider mismatch")
    return payload


async def validate_oauth_state_replay(state_payload: dict[str, Any]) -> None:
    jti = str(state_payload.get("jti") or "")
    if not jti:
        raise PaypalAccountError("OAuth state missing replay guard")
    if not await consume_oauth_jti(jti, ttl_seconds=STATE_TTL_SECONDS):
        raise PaypalAccountError("OAuth state already used")


async def get_paypal_account_for_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> TenantPaymentProviderAccount | None:
    """Active (non-disconnected) PayPal connection for the tenant."""
    return (
        await db.execute(
            select(TenantPaymentProviderAccount).where(
                TenantPaymentProviderAccount.tenant_id == tenant_id,
                TenantPaymentProviderAccount.provider == PROVIDER_PAYPAL,
                TenantPaymentProviderAccount.status != STATUS_DISCONNECTED,
            )
        )
    ).scalar_one_or_none()


async def _get_any_paypal_row_for_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> TenantPaymentProviderAccount | None:
    """Any PayPal row for the tenant, including disconnected (for idempotent upsert)."""
    return (
        await db.execute(
            select(TenantPaymentProviderAccount)
            .where(
                TenantPaymentProviderAccount.tenant_id == tenant_id,
                TenantPaymentProviderAccount.provider == PROVIDER_PAYPAL,
            )
            .order_by(TenantPaymentProviderAccount.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _sandbox_test_account_id(tenant_id: uuid.UUID) -> str:
    """Tenant-scoped sandbox identity — never the shared PAYPAL_SANDBOX_MERCHANT_ID."""
    return f"sandbox-test:{tenant_id}"


def _already_connected_payload(
    account: TenantPaymentProviderAccount,
    *,
    mode: str,
) -> dict[str, Any]:
    readiness = readiness_payload(account)
    return {
        "connected": True,
        "already_connected": True,
        "mode": mode,
        "action": "already_connected",
        "merchant_id": readiness.get("merchant_id"),
        "redirect_url": None,
        "readiness": readiness,
    }


def readiness_payload(
    account: TenantPaymentProviderAccount | None,
    *,
    configured: bool | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    is_configured = settings.paypal_configured if configured is None else configured
    if account is None:
        return {
            "configured": is_configured,
            "connected": False,
            "merchant_id": None,
            "display_name": None,
            "onboarding_complete": False,
            "payments_enabled": False,
            "payouts_enabled": False,
            "balance_available": False,
            "transactions_available": False,
            "needs_reauthorization": False,
            "last_verified_at": None,
            "last_error": None,
        }

    onboarding_complete = (account.onboarding_status or "") in (
        ONBOARDING_COMPLETE,
        ONBOARDING_SANDBOX_TEST,
    )
    last_error = None
    if account.last_error_code or account.last_error_message:
        last_error = {
            "code": account.last_error_code,
            "message": account.last_error_message,
        }

    return {
        "configured": is_configured,
        "connected": account.status == STATUS_CONNECTED,
        "merchant_id": account.provider_merchant_id or account.provider_account_id,
        "display_name": account.display_name,
        "onboarding_complete": onboarding_complete,
        "payments_enabled": bool(account.payments_enabled),
        "payouts_enabled": bool(account.payouts_enabled)
        and bool(settings.paypal_payouts_enabled),
        "balance_available": bool(account.balance_visibility)
        and bool(settings.paypal_balance_enabled),
        "transactions_available": bool(account.transactions_visibility)
        and bool(settings.paypal_transaction_search_enabled),
        "needs_reauthorization": account.status == "needs_reauth",
        "last_verified_at": account.last_verified_at.isoformat()
        if account.last_verified_at
        else None,
        "last_error": last_error,
    }


async def get_paypal_readiness(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    account = await get_paypal_account_for_tenant(db, tenant_id)
    return readiness_payload(account)


async def connect_paypal_account(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
) -> dict[str, Any]:
    """Start partner onboarding or explicit sandbox platform-test connect."""
    settings = get_settings()
    if not settings.paypal_configured:
        raise PaypalAccountError("PayPal is not configured", code="paypal_not_configured")

    existing = await get_paypal_account_for_tenant(db, tenant_id)
    if existing is not None and existing.status == STATUS_CONNECTED:
        mode = (
            "sandbox_test"
            if (existing.onboarding_status or "") == ONBOARDING_SANDBOX_TEST
            else "partner_onboarding"
        )
        return _already_connected_payload(existing, mode=mode)

    if not settings.paypal_partner_onboarding_enabled:
        # Explicit sandbox platform testing only — requires the env gate to be set,
        # but never stores PAYPAL_SANDBOX_MERCHANT_ID as the tenant's merchant identity.
        sandbox_gate = settings.paypal_sandbox_merchant_id.strip()
        if settings.paypal_mode_normalized == "sandbox" and sandbox_gate:
            return await _connect_sandbox_test_mode(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        raise PaypalAccountError(
            "PayPal partner onboarding is not enabled for this environment",
            code="capability_required",
        )

    return await _start_partner_referral(db, tenant_id=tenant_id, user_id=user_id)


async def _connect_sandbox_test_mode(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
) -> dict[str, Any]:
    """Idempotent platform sandbox test connect (not seller Partner Referral).

    Uses a tenant-scoped provider_account_id so reconnect never collides on the
    shared PAYPAL_SANDBOX_MERCHANT_ID unique key.
    """
    now = datetime.now(timezone.utc)
    account_id = _sandbox_test_account_id(tenant_id)

    account = await get_paypal_account_for_tenant(db, tenant_id)
    if account is not None and account.status == STATUS_CONNECTED:
        return _already_connected_payload(account, mode="sandbox_test")

    # Reuse disconnected/pending row when present — never INSERT a duplicate.
    account = await _get_any_paypal_row_for_tenant(db, tenant_id)
    created = False
    if account is None:
        account = TenantPaymentProviderAccount(
            tenant_id=tenant_id,
            provider=PROVIDER_PAYPAL,
            provider_account_id=account_id,
        )
        db.add(account)
        created = True

    account.provider_account_id = account_id
    # Platform sandbox merchant is an env gate only — not the seller merchant id.
    account.provider_merchant_id = account_id
    account.display_name = "PayPal Sandbox (platform test)"
    account.status = STATUS_CONNECTED
    account.onboarding_status = ONBOARDING_SANDBOX_TEST
    account.payments_enabled = True
    account.payouts_enabled = bool(get_settings().paypal_payouts_enabled)
    account.balance_visibility = bool(get_settings().paypal_balance_enabled)
    account.transactions_visibility = bool(
        get_settings().paypal_transaction_search_enabled
    )
    account.last_verified_at = now
    account.last_balance_sync_at = None
    account.last_transaction_sync_at = None
    account.last_error_code = None
    account.last_error_message = None
    account.tracking_id = account.tracking_id or str(uuid.uuid4())
    account.encrypted_access_token = None
    account.encrypted_refresh_token = None
    account.token_expires_at = None
    await db.flush()

    await log_event(
        db,
        "paypal_sandbox_connected",
        tenant_id=tenant_id,
        detail={
            "merchant_id": account_id,
            "user_id": user_id,
            "mode": "sandbox_test",
            "created": created,
        },
    )
    return {
        "connected": True,
        "already_connected": False,
        "mode": "sandbox_test",
        "action": "connected",
        "merchant_id": account_id,
        "redirect_url": None,
        "readiness": readiness_payload(account),
    }


async def _start_partner_referral(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
) -> dict[str, Any]:
    settings = get_settings()
    return_url = settings.paypal_return_url.strip()
    cancel_url = settings.paypal_cancel_url.strip()
    if not return_url or not cancel_url:
        raise PaypalAccountError(
            "PAYPAL_RETURN_URL and PAYPAL_CANCEL_URL must be configured",
            code="paypal_urls_required",
        )

    active = await get_paypal_account_for_tenant(db, tenant_id)
    if active is not None and active.status == STATUS_CONNECTED:
        return _already_connected_payload(active, mode="partner_onboarding")

    state = create_oauth_state(tenant_id=tenant_id, user_id=user_id)
    tracking_id = str(uuid.uuid4())

    # Upsert pending row (reuse disconnected row) — seller merchant id comes from callback.
    account = await _get_any_paypal_row_for_tenant(db, tenant_id)
    if account is None:
        account = TenantPaymentProviderAccount(
            tenant_id=tenant_id,
            provider=PROVIDER_PAYPAL,
            provider_account_id=f"pending:{tracking_id}",
        )
        db.add(account)
    else:
        account.provider_account_id = f"pending:{tracking_id}"
        account.provider_merchant_id = None

    account.tracking_id = tracking_id
    account.status = STATUS_PENDING
    account.onboarding_status = ONBOARDING_PENDING
    account.payments_enabled = False
    account.payouts_enabled = False
    account.balance_visibility = False
    account.transactions_visibility = False
    account.display_name = None
    account.last_error_code = None
    account.last_error_message = None
    account.encrypted_access_token = None
    account.encrypted_refresh_token = None
    account.token_expires_at = None
    await db.flush()

    body = {
        "tracking_id": tracking_id,
        "partner_config_override": {
            "return_url": f"{return_url}?{urlencode({'state': state})}",
            "return_url_description": "Return to LedgerLink",
            "show_add_credit_card": True,
        },
        "operations": [
            {
                "operation": "API_INTEGRATION",
                "api_integration_preference": {
                    "rest_api_integration": {
                        "integration_method": "PAYPAL",
                        "integration_type": "THIRD_PARTY",
                        "third_party_details": {
                            "features": [
                                "PAYMENT",
                                "REFUND",
                                "PARTNER_FEE",
                                "ACCESS_MERCHANT_INFORMATION",
                            ]
                        },
                    }
                },
            }
        ],
        "products": ["EXPRESS_CHECKOUT", "PPPLUS"],
        "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}],
    }

    client = get_paypal_client()
    try:
        payload = await client.request_json(
            "POST",
            "/v2/customer/partner-referrals",
            json=body,
            paypal_request_id=f"partner-ref-{tracking_id}",
        )
    except PaypalApiError as exc:
        account.last_error_code = exc.error_code or "partner_referral_failed"
        account.last_error_message = str(exc)[:512]
        await db.flush()
        raise PaypalAccountError(str(exc), code=exc.error_code) from exc

    redirect_url = None
    for link in payload.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "action_url":
            redirect_url = link.get("href")
            break
    if not redirect_url:
        raise PaypalAccountError(
            "PayPal partner referral did not return an action URL",
            code="partner_referral_incomplete",
        )

    await log_event(
        db,
        "paypal_partner_referral_started",
        tenant_id=tenant_id,
        detail={"tracking_id": tracking_id, "user_id": user_id},
    )
    return {
        "connected": False,
        "already_connected": False,
        "mode": "partner_onboarding",
        "action": "redirect",
        "redirect_url": redirect_url,
        "tracking_id": tracking_id,
        "state": state,
        "readiness": readiness_payload(account),
    }


async def handle_paypal_oauth_callback(
    db: AsyncSession,
    *,
    state: str,
    merchant_id: str | None = None,
    tracking_id: str | None = None,
) -> dict[str, Any]:
    """Complete partner onboarding callback; merchant_id is the stable external id."""
    payload = parse_oauth_state(state)
    await validate_oauth_state_replay(payload)

    tenant_id = parse_tenant_id(payload.get("org_id"))
    if tenant_id is None:
        raise PaypalAccountError("Invalid tenant in OAuth state")

    user_id = int(payload.get("sub") or 0)
    resolved_merchant = (merchant_id or "").strip()
    resolved_tracking = (tracking_id or "").strip()

    account = None
    if resolved_tracking:
        account = (
            await db.execute(
                select(TenantPaymentProviderAccount).where(
                    TenantPaymentProviderAccount.tenant_id == tenant_id,
                    TenantPaymentProviderAccount.provider == PROVIDER_PAYPAL,
                    TenantPaymentProviderAccount.tracking_id == resolved_tracking,
                )
            )
        ).scalar_one_or_none()
    if account is None:
        account = await get_paypal_account_for_tenant(db, tenant_id)
    if account is None:
        raise PaypalAccountError("PayPal onboarding session not found")

    if not resolved_merchant:
        # Attempt to resolve merchant id from partner referral status when possible.
        if account.tracking_id:
            resolved_merchant = await _fetch_merchant_id_for_tracking(
                account.tracking_id
            ) or ""

    if not resolved_merchant:
        account.status = STATUS_PENDING
        account.onboarding_status = ONBOARDING_PENDING
        account.last_error_code = "merchant_id_missing"
        account.last_error_message = "PayPal callback missing merchant id"
        await db.flush()
        raise PaypalAccountError(
            "PayPal merchant id is required to complete connection",
            code="merchant_id_required",
        )

    now = datetime.now(timezone.utc)
    account.provider_account_id = resolved_merchant
    account.provider_merchant_id = resolved_merchant
    account.status = STATUS_CONNECTED
    account.onboarding_status = ONBOARDING_COMPLETE
    account.payments_enabled = True
    account.payouts_enabled = bool(get_settings().paypal_payouts_enabled)
    account.balance_visibility = bool(get_settings().paypal_balance_enabled)
    account.transactions_visibility = bool(
        get_settings().paypal_transaction_search_enabled
    )
    account.last_verified_at = now
    account.last_error_code = None
    account.last_error_message = None
    await db.flush()

    await log_event(
        db,
        "paypal_account_connected",
        tenant_id=tenant_id,
        detail={
            "merchant_id": resolved_merchant,
            "user_id": user_id,
            "tracking_id": account.tracking_id,
        },
    )
    return readiness_payload(account)


async def _fetch_merchant_id_for_tracking(tracking_id: str) -> str | None:
    settings = get_settings()
    partner_id = settings.paypal_partner_merchant_id.strip()
    if not partner_id:
        return None
    client = get_paypal_client()
    try:
        payload = await client.request_json(
            "GET",
            f"/v1/customer/partners/{partner_id}/merchant-integrations",
            params={"tracking_id": tracking_id},
        )
    except PaypalApiError:
        return None
    merchant = (
        payload.get("merchant_id")
        or payload.get("payer_id")
        or (payload.get("merchant_integrations") or [{}])[0].get("merchant_id")
    )
    return str(merchant).strip() if merchant else None


def store_encrypted_account_tokens(
    account: TenantPaymentProviderAccount,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    """Persist merchant tokens encrypted at rest. Never log token values."""
    if access_token:
        account.encrypted_access_token = encrypt_secret(access_token)
    if refresh_token:
        account.encrypted_refresh_token = encrypt_secret(refresh_token)
    if expires_at is not None:
        account.token_expires_at = expires_at


async def disconnect_paypal_account(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Deactivate the tenant PayPal connection; keep historical payment attempts."""
    account = await _get_any_paypal_row_for_tenant(db, tenant_id)
    if account is None or account.status == STATUS_DISCONNECTED:
        raise PaypalAccountError("PayPal account is not connected")

    prior_merchant = account.provider_merchant_id or account.provider_account_id
    # Rotate account id so a later reconnect with the same seller id cannot collide.
    account.provider_account_id = f"disconnected:{uuid.uuid4()}"
    account.provider_merchant_id = None
    account.provider_email = None
    account.display_name = None
    account.status = STATUS_DISCONNECTED
    account.onboarding_status = None
    account.payments_enabled = False
    account.payouts_enabled = False
    account.balance_visibility = False
    account.transactions_visibility = False
    account.encrypted_access_token = None
    account.encrypted_refresh_token = None
    account.token_expires_at = None
    account.tracking_id = None
    account.last_verified_at = None
    account.last_balance_sync_at = None
    account.last_transaction_sync_at = None
    account.last_error_code = None
    account.last_error_message = None
    await db.flush()

    await log_event(
        db,
        "paypal_account_disconnected",
        tenant_id=tenant_id,
        detail={"merchant_id": prior_merchant, "user_id": user_id},
    )
    # Readiness is computed live from DB — disconnected rows are excluded.
    return readiness_payload(None, configured=get_settings().paypal_configured)
