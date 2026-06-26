"""Stripe Connect helpers - account onboarding, balance, transactions, webhooks."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import jwt
import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.stripe_payments import (
    StripeAccount,
    StripeBalanceSnapshot,
    StripeTransaction,
    StripeWebhookEvent,
)
from app.models.tenant import Tenant
from app.tenant_ids import parse_tenant_id
from app.tenant_scoped import coerce_tenant_uuid
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Phase 2: external supplier bank payout via Connect transfers / vendor_payment_methods.
_VENDOR_BANK_PAYOUT_PHASE = 2

STRIPE_OAUTH_STATE_TYP = "stripe_connect_oauth"
STRIPE_OAUTH_STATE_TTL_MINUTES = 15
STRIPE_OAUTH_AUTHORIZE_URL = "https://connect.stripe.com/oauth/authorize"
STRIPE_ONBOARDING_STATUS_DISCONNECTED = "disconnected"


class StripeServiceError(Exception):
    """Safe application error for Stripe configuration or API failures."""


@dataclass(frozen=True)
class StripeBalanceSummary:
    available: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    livemode: bool
    snapshot_id: int


@dataclass(frozen=True)
class StripeTransactionSummary:
    id: int
    stripe_transaction_id: str
    type: str | None
    amount: float | None
    currency: str | None
    status: str | None
    description: str | None
    available_on: str | None


@dataclass(frozen=True)
class WebhookRecordResult:
    event: StripeWebhookEvent
    duplicate: bool
    already_processed: bool


def _require_stripe_configured(settings: Settings | None = None) -> Settings:
    cfg = settings or get_settings()
    if not cfg.stripe_configured:
        raise StripeServiceError("Stripe is not configured")
    return cfg


def _require_stripe_oauth_configured(settings: Settings | None = None) -> Settings:
    cfg = _require_stripe_configured(settings)
    if not cfg.stripe_connect_client_id.strip():
        raise StripeServiceError("Stripe Connect client ID is not configured")
    if not cfg.stripe_oauth_redirect_url.strip():
        raise StripeServiceError("Stripe OAuth redirect URL is not configured")
    if not cfg.jwt_secret.strip():
        raise StripeServiceError("JWT secret is not configured")
    return cfg


def _configure_stripe(settings: Settings | None = None) -> Settings:
    cfg = _require_stripe_configured(settings)
    stripe.api_key = cfg.stripe_secret_key
    return cfg


def _stripe_object_to_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "to_dict_recursive"):
        return obj.to_dict_recursive()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, dict):
        return obj
    return dict(obj)


def _cents_to_decimal(amount: int | None) -> Decimal | None:
    if amount is None:
        return None
    return Decimal(amount) / Decimal(100)


def _balance_amounts_to_safe(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in items or []:
        amount = item.get("amount")
        safe.append(
            {
                "amount": float(_cents_to_decimal(amount)) if amount is not None else None,
                "currency": item.get("currency"),
            }
        )
    return safe


def _derive_onboarding_status(account: Any) -> str:
    if not bool(getattr(account, "details_submitted", False)):
        return "pending"
    if bool(getattr(account, "charges_enabled", False)) and bool(
        getattr(account, "payouts_enabled", False)
    ):
        return "complete"
    return "action_required"


def _is_active_stripe_account(row: StripeAccount | None) -> bool:
    if row is None:
        return False
    return row.onboarding_status != STRIPE_ONBOARDING_STATUS_DISCONNECTED


def _account_row_from_stripe(
    row: StripeAccount,
    account: Any,
    *,
    tenant_id: uuid.UUID,
) -> StripeAccount:
    row.tenant_id = tenant_id
    row.stripe_account_id = account.id
    row.account_type = getattr(account, "type", None)
    row.charges_enabled = bool(getattr(account, "charges_enabled", False))
    row.payouts_enabled = bool(getattr(account, "payouts_enabled", False))
    row.details_submitted = bool(getattr(account, "details_submitted", False))
    row.onboarding_status = _derive_onboarding_status(account)
    return row


def _create_stripe_express_account(*, tenant_id: uuid.UUID, tenant_name: str | None) -> Any:
    params: dict[str, Any] = {
        "type": "express",
        "country": "AU",
        "capabilities": {
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        "metadata": {"tenant_id": str(tenant_id)},
    }
    if tenant_name:
        params["business_profile"] = {"name": tenant_name[:255]}
    return stripe.Account.create(**params)


def _retrieve_stripe_account(stripe_account_id: str) -> Any:
    return stripe.Account.retrieve(stripe_account_id)


def _create_stripe_account_link(
    stripe_account_id: str,
    *,
    return_url: str,
    refresh_url: str,
) -> Any:
    return stripe.AccountLink.create(
        account=stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )


def _retrieve_stripe_balance(stripe_account_id: str) -> Any:
    return stripe.Balance.retrieve(stripe_account=stripe_account_id)


def _list_stripe_balance_transactions(stripe_account_id: str, *, limit: int) -> Any:
    return stripe.BalanceTransaction.list(
        limit=limit,
        stripe_account=stripe_account_id,
    )


def _verify_stripe_webhook_event(
    payload: bytes,
    signature: str,
    webhook_secret: str,
) -> Any:
    return stripe.Webhook.construct_event(payload, signature, webhook_secret)


async def _run_stripe(callable_obj, *args, **kwargs):
    return await asyncio.to_thread(callable_obj, *args, **kwargs)


def create_stripe_oauth_state(
    *,
    tenant_id: uuid.UUID | str | int,
    user_id: int | None = None,
) -> str:
    """Signed OAuth state binding tenant (and optional user) for the callback."""
    _require_stripe_oauth_configured()
    tid = coerce_tenant_uuid(tenant_id)
    expire = datetime.now(timezone.utc) + timedelta(minutes=STRIPE_OAUTH_STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": STRIPE_OAUTH_STATE_TYP,
        "org_id": str(tid),
        "exp": expire,
    }
    if user_id is not None:
        payload["user_id"] = user_id
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_stripe_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != STRIPE_OAUTH_STATE_TYP:
        raise ValueError("Invalid Stripe OAuth state")
    tenant_id = parse_tenant_id(payload.get("org_id"))
    if tenant_id is None:
        raise ValueError("Invalid tenant in Stripe OAuth state")
    payload["tenant_id"] = tenant_id
    return payload


def create_stripe_oauth_url(tenant_id: uuid.UUID | str | int, state: str) -> str:
    """Build Stripe Connect OAuth authorize URL for an existing Standard account."""
    cfg = _require_stripe_oauth_configured()
    tid = coerce_tenant_uuid(tenant_id)
    redirect_uri = cfg.stripe_oauth_redirect_url.strip()
    client_id = cfg.stripe_connect_client_id.strip()
    if not state.strip():
        raise StripeServiceError("Stripe OAuth state is required")

    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    logger.info("stripe_oauth_authorize_url_created", tenant_id=str(tid))
    return f"{STRIPE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def _exchange_stripe_oauth_code(code: str) -> dict[str, Any]:
    return _stripe_object_to_dict(stripe.OAuth.token(grant_type="authorization_code", code=code))


async def exchange_stripe_oauth_code(
    db: AsyncSession,
    tenant_id: uuid.UUID | int,
    code: str,
) -> StripeAccount:
    """Exchange OAuth authorization code and link an existing Standard connected account."""
    cfg = _require_stripe_oauth_configured()
    tid = coerce_tenant_uuid(tenant_id)
    if not code.strip():
        raise StripeServiceError("Stripe OAuth authorization code is required")

    def _token() -> dict[str, Any]:
        _configure_stripe(cfg)
        return _exchange_stripe_oauth_code(code)

    try:
        token_response = await _run_stripe(_token)
    except stripe.StripeError as exc:
        logger.warning("stripe_oauth_token_failed", tenant_id=str(tid), error=str(exc))
        raise StripeServiceError("Unable to complete Stripe OAuth connection") from exc

    stripe_user_id = str(token_response.get("stripe_user_id") or "")
    if not stripe_user_id:
        raise StripeServiceError("Stripe OAuth response missing connected account id")

    existing_row = await _get_stripe_account_row_for_tenant(db, tid)
    if existing_row is not None and _is_active_stripe_account(existing_row):
        if existing_row.stripe_account_id != stripe_user_id:
            raise StripeServiceError("Tenant already has a different Stripe connected account")
        row = existing_row
    elif existing_row is not None:
        row = existing_row
        row.stripe_account_id = stripe_user_id
    else:
        row = StripeAccount(tenant_id=tid, stripe_account_id=stripe_user_id)
        db.add(row)

    row.account_type = "standard"
    await db.flush()

    try:
        row = await refresh_connected_account_status(db, row)
    except StripeServiceError:
        row.account_type = "standard"
        if not row.onboarding_status:
            row.onboarding_status = "complete"
        await db.flush()

    logger.info(
        "stripe_oauth_account_linked",
        tenant_id=str(tid),
        stripe_account_id=row.stripe_account_id,
        account_type=row.account_type,
        onboarding_status=row.onboarding_status,
    )
    return row


async def _get_stripe_account_row_for_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID | int,
) -> StripeAccount | None:
    tid = coerce_tenant_uuid(tenant_id)
    return (
        await db.execute(select(StripeAccount).where(StripeAccount.tenant_id == tid))
    ).scalar_one_or_none()


async def get_stripe_account_for_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID | int,
) -> StripeAccount | None:
    row = await _get_stripe_account_row_for_tenant(db, tenant_id)
    if not _is_active_stripe_account(row):
        return None
    return row


async def disconnect_stripe_account_for_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID | int,
) -> StripeAccount:
    """Locally unlink the tenant Stripe account without deleting Stripe-side data."""
    tid = coerce_tenant_uuid(tenant_id)
    row = await _get_stripe_account_row_for_tenant(db, tid)
    if row is None or not _is_active_stripe_account(row):
        raise StripeServiceError("Stripe connected account not found")

    row.onboarding_status = STRIPE_ONBOARDING_STATUS_DISCONNECTED
    row.charges_enabled = False
    row.payouts_enabled = False
    row.details_submitted = False
    await db.flush()

    logger.info(
        "stripe_account_disconnected",
        tenant_id=str(tid),
        stripe_account_id=row.stripe_account_id,
        account_type=row.account_type,
    )
    return row


async def create_connected_account_for_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID | int,
    tenant_name: str | None = None,
) -> StripeAccount:
    """Create or refresh the tenant's Stripe Connect Express account."""
    cfg = _require_stripe_configured()
    tid = coerce_tenant_uuid(tenant_id)

    existing_row = await _get_stripe_account_row_for_tenant(db, tid)
    if existing_row is not None and _is_active_stripe_account(existing_row):
        return await refresh_connected_account_status(db, existing_row)

    if existing_row is not None and existing_row.account_type == "express":
        try:
            return await refresh_connected_account_status(db, existing_row)
        except StripeServiceError:
            logger.info(
                "stripe_express_reconnect_refresh_failed",
                tenant_id=str(tid),
                stripe_account_id=existing_row.stripe_account_id,
            )

    if tenant_name is None:
        tenant = await db.get(Tenant, tid)
        if tenant is not None:
            tenant_name = tenant.name

    def _create() -> Any:
        _configure_stripe(cfg)
        return _create_stripe_express_account(tenant_id=tid, tenant_name=tenant_name)

    try:
        account = await _run_stripe(_create)
    except stripe.StripeError as exc:
        logger.warning("stripe_account_create_failed", tenant_id=str(tid), error=str(exc))
        raise StripeServiceError("Unable to create Stripe connected account") from exc

    if existing_row is not None:
        row = existing_row
        row.stripe_account_id = account.id
        _account_row_from_stripe(row, account, tenant_id=tid)
    else:
        row = StripeAccount(tenant_id=tid, stripe_account_id=account.id)
        _account_row_from_stripe(row, account, tenant_id=tid)
        db.add(row)
    await db.flush()

    logger.info(
        "stripe_account_created",
        tenant_id=str(tid),
        stripe_account_id=row.stripe_account_id,
        account_type=row.account_type,
    )
    return row


async def create_account_onboarding_link(stripe_account_id: str) -> str:
    """Return a one-time Stripe Account Link URL for Connect onboarding."""
    cfg = _require_stripe_configured()
    return_url = cfg.stripe_return_url.strip()
    refresh_url = cfg.stripe_refresh_url.strip()
    if not return_url or not refresh_url:
        raise StripeServiceError("Stripe return and refresh URLs are not configured")

    def _create_link() -> Any:
        _configure_stripe(cfg)
        return _create_stripe_account_link(
            stripe_account_id,
            return_url=return_url,
            refresh_url=refresh_url,
        )

    try:
        link = await _run_stripe(_create_link)
    except stripe.StripeError as exc:
        logger.warning(
            "stripe_account_link_failed",
            stripe_account_id=stripe_account_id,
            error=str(exc),
        )
        raise StripeServiceError("Unable to create Stripe onboarding link") from exc

    url = str(getattr(link, "url", "") or "")
    if not url:
        raise StripeServiceError("Stripe onboarding link did not return a URL")
    return url


async def refresh_connected_account_status(
    db: AsyncSession,
    stripe_account: StripeAccount,
) -> StripeAccount:
    """Retrieve account state from Stripe and update the local row."""
    cfg = _require_stripe_configured()

    def _retrieve() -> Any:
        _configure_stripe(cfg)
        return _retrieve_stripe_account(stripe_account.stripe_account_id)

    try:
        account = await _run_stripe(_retrieve)
    except stripe.StripeError as exc:
        logger.warning(
            "stripe_account_refresh_failed",
            tenant_id=str(stripe_account.tenant_id),
            stripe_account_id=stripe_account.stripe_account_id,
            error=str(exc),
        )
        raise StripeServiceError("Unable to refresh Stripe account status") from exc

    _account_row_from_stripe(stripe_account, account, tenant_id=stripe_account.tenant_id)
    await db.flush()
    return stripe_account


async def get_connected_account_balance(
    db: AsyncSession,
    tenant_id: uuid.UUID | int,
    stripe_account_id: str,
) -> StripeBalanceSummary:
    """Fetch balance from Stripe and persist a snapshot."""
    cfg = _require_stripe_configured()
    tid = coerce_tenant_uuid(tenant_id)

    local_account = await get_stripe_account_for_tenant(db, tid)
    if local_account is None or local_account.stripe_account_id != stripe_account_id:
        raise StripeServiceError("Stripe connected account not found for tenant")

    def _retrieve() -> Any:
        _configure_stripe(cfg)
        return _retrieve_stripe_balance(stripe_account_id)

    try:
        balance = await _run_stripe(_retrieve)
    except stripe.StripeError as exc:
        logger.warning(
            "stripe_balance_failed",
            tenant_id=str(tid),
            stripe_account_id=stripe_account_id,
            error=str(exc),
        )
        raise StripeServiceError("Unable to retrieve Stripe balance") from exc

    balance_dict = _stripe_object_to_dict(balance)
    available = balance_dict.get("available") or []
    pending = balance_dict.get("pending") or []
    livemode = bool(balance_dict.get("livemode", not cfg.stripe_sandbox_mode))

    snapshot = StripeBalanceSnapshot(
        tenant_id=tid,
        stripe_account_id=stripe_account_id,
        available_json=available,
        pending_json=pending,
        livemode=livemode,
    )
    db.add(snapshot)
    await db.flush()

    return StripeBalanceSummary(
        available=_balance_amounts_to_safe(available),
        pending=_balance_amounts_to_safe(pending),
        livemode=livemode,
        snapshot_id=snapshot.id,
    )


def _transaction_summary_from_row(row: StripeTransaction) -> StripeTransactionSummary:
    return StripeTransactionSummary(
        id=row.id,
        stripe_transaction_id=row.stripe_transaction_id,
        type=row.type,
        amount=float(row.amount) if row.amount is not None else None,
        currency=row.currency,
        status=row.status,
        description=row.description,
        available_on=row.available_on.isoformat() if row.available_on else None,
    )


async def _upsert_transaction_row(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    stripe_account_id: str,
    txn: Any,
) -> StripeTransaction:
    txn_dict = _stripe_object_to_dict(txn)
    stripe_transaction_id = str(txn_dict.get("id") or "")
    if not stripe_transaction_id:
        raise StripeServiceError("Stripe balance transaction missing id")

    available_on_raw = txn_dict.get("available_on")
    available_on: date | None = None
    if available_on_raw is not None:
        available_on = date.fromtimestamp(int(available_on_raw))

    values = {
        "tenant_id": tenant_id,
        "stripe_account_id": stripe_account_id,
        "type": txn_dict.get("type"),
        "amount": _cents_to_decimal(txn_dict.get("amount")),
        "currency": txn_dict.get("currency"),
        "status": txn_dict.get("status"),
        "description": txn_dict.get("description"),
        "available_on": available_on,
        "raw_json": txn_dict,
    }

    existing = (
        await db.execute(
            select(StripeTransaction).where(
                StripeTransaction.stripe_transaction_id == stripe_transaction_id
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        row = StripeTransaction(
            stripe_transaction_id=stripe_transaction_id,
            **values,
        )
        db.add(row)
        await db.flush()
        return row

    for key, value in values.items():
        setattr(existing, key, value)
    await db.flush()
    return existing


async def list_connected_account_transactions(
    db: AsyncSession,
    tenant_id: uuid.UUID | int,
    stripe_account_id: str,
    limit: int = 20,
) -> list[StripeTransactionSummary]:
    """List recent balance transactions and upsert local StripeTransaction rows."""
    cfg = _require_stripe_configured()
    tid = coerce_tenant_uuid(tenant_id)

    local_account = await get_stripe_account_for_tenant(db, tid)
    if local_account is None or local_account.stripe_account_id != stripe_account_id:
        raise StripeServiceError("Stripe connected account not found for tenant")

    capped_limit = max(1, min(limit, 100))

    def _list_txns() -> Any:
        _configure_stripe(cfg)
        return _list_stripe_balance_transactions(stripe_account_id, limit=capped_limit)

    try:
        listing = await _run_stripe(_list_txns)
    except stripe.StripeError as exc:
        logger.warning(
            "stripe_transactions_failed",
            tenant_id=str(tid),
            stripe_account_id=stripe_account_id,
            error=str(exc),
        )
        raise StripeServiceError("Unable to list Stripe balance transactions") from exc

    rows: list[StripeTransactionSummary] = []
    for txn in getattr(listing, "data", []) or []:
        row = await _upsert_transaction_row(
            db,
            tenant_id=tid,
            stripe_account_id=stripe_account_id,
            txn=txn,
        )
        rows.append(_transaction_summary_from_row(row))
    return rows


def verify_stripe_webhook(payload: bytes, signature: str) -> Any:
    """Validate Stripe webhook signature and return the parsed event."""
    cfg = _require_stripe_configured()
    if not cfg.stripe_webhook_secret.strip():
        raise StripeServiceError("Stripe webhook secret is not configured")
    if not signature.strip():
        raise StripeServiceError("Missing Stripe webhook signature")

    try:
        _configure_stripe(cfg)
        return _verify_stripe_webhook_event(
            payload,
            signature,
            cfg.stripe_webhook_secret,
        )
    except stripe.SignatureVerificationError as exc:
        raise StripeServiceError("Invalid Stripe webhook signature") from exc
    except ValueError as exc:
        raise StripeServiceError("Invalid Stripe webhook payload") from exc


async def record_webhook_event_once(db: AsyncSession, event: Any) -> WebhookRecordResult:
    """Persist webhook event once; duplicates return existing row."""
    event_id = str(getattr(event, "id", "") or "")
    event_type = str(getattr(event, "type", "") or "")
    if not event_id or not event_type:
        raise StripeServiceError("Stripe webhook event missing id or type")

    existing = (
        await db.execute(
            select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return WebhookRecordResult(
            event=existing,
            duplicate=True,
            already_processed=existing.processed_at is not None,
        )

    payload = _stripe_object_to_dict(event)
    row = StripeWebhookEvent(
        stripe_event_id=event_id,
        event_type=event_type,
        payload_json=payload,
        processed_at=None,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        existing = (
            await db.execute(
                select(StripeWebhookEvent).where(
                    StripeWebhookEvent.stripe_event_id == event_id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise StripeServiceError("Unable to record Stripe webhook event")
        return WebhookRecordResult(
            event=existing,
            duplicate=True,
            already_processed=existing.processed_at is not None,
        )

    logger.info("stripe_webhook_recorded", stripe_event_id=event_id, event_type=event_type)
    return WebhookRecordResult(event=row, duplicate=False, already_processed=False)
