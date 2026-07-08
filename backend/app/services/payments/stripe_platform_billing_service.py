"""LedgerLink platform billing via Stripe Checkout (subscriptions + top-ups)."""

from __future__ import annotations

import asyncio
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import stripe
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.auth_account import AuthAccount
from app.models.pending_signup_billing import PendingSignupBillingSession
from app.models.platform_billing_webhook import PlatformBillingWebhookEvent
from app.models.tenant import Tenant
from app.models.tenant_billing import TenantBilling
from app.models.user import User, UserRole
from app.services.auth.auth_service import hash_password
from app.services.auth.membership_service import ensure_membership
from app.services.credit_catalog import (
    PLAN_ENTERPRISE,
    PLAN_FREE,
    PLAN_STUDIO,
    list_country_plans,
    plan_definition,
    pricing_region_for_country,
    region_currency,
    tenant_pricing_region,
)
from app.services.credit_service import (
    apply_studio_subscription_to_billing,
    ensure_tenant_billing,
    get_platform_credit_settings,
    grant_credits_idempotent,
    refresh_tenant_billing,
    topup_factor_key,
)
from app.services.payments.stripe_service import StripeServiceError
from app.services.rule_book.rule_book_config_repository import ensure_default_config
from app.services.tenant.platform_service import _seed_modules
from app.tenant_rls import apply_platform_lookup_session, clear_platform_lookup_session, apply_rls_session_context
from app.tenant_settings import build_tenant_settings, tenant_country
from app.services.shared.public_app_url import build_public_app_path
from app.tenant_roles import TenantRole
from app.utils.logger import get_logger

logger = get_logger(__name__)

SIGNUP_STATUS_PENDING = "pending"
SIGNUP_STATUS_COMPLETED = "completed"
SIGNUP_STATUS_EXPIRED = "expired"
SIGNUP_STATUS_FAILED = "failed"

SIGNUP_SOURCE_PUBLIC = "public"
SIGNUP_SOURCE_INVITE = "invite"

EVENT_CREDIT_TOPUP = "credit_topup"
EVENT_PLAN_UPGRADE = "plan_upgrade"


@dataclass(frozen=True)
class CheckoutSessionResult:
    checkout_url: str | None
    session_id: str | None
    status: str
    pending_signup_id: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True)
class SignupFreeResult:
    tenant_id: uuid.UUID
    signup_token: str


@dataclass(frozen=True)
class WebhookRecordResult:
    event: PlatformBillingWebhookEvent
    duplicate: bool
    already_processed: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _configure_stripe(settings: Settings | None = None) -> Settings:
    cfg = settings or get_settings()
    if not cfg.stripe_secret_key.strip():
        raise StripeServiceError("Stripe is not configured")
    stripe.api_key = cfg.stripe_secret_key.strip()
    return cfg


def _stripe_object_to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return dict(obj)


def _unix_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _checkout_return_url(base: str) -> str:
    base = base.strip()
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}session_id={{CHECKOUT_SESSION_ID}}"


def _slugify_org(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return slug.strip("-")[:100] or "organisation"


async def _run_stripe(callable_obj, *args, **kwargs):
    return await asyncio.to_thread(callable_obj, *args, **kwargs)


def _require_platform_billing(settings: Settings | None = None) -> Settings:
    cfg = settings or get_settings()
    if not cfg.stripe_platform_billing_active:
        raise HTTPException(503, "Platform billing is not enabled")
    return cfg


def verify_platform_billing_webhook(payload: bytes, signature: str) -> Any:
    cfg = _configure_stripe()
    secret = cfg.stripe_platform_billing_webhook_secret.strip()
    if not secret:
        raise StripeServiceError("Platform billing webhook secret is not configured")
    if not signature.strip():
        raise StripeServiceError("Missing Stripe webhook signature")
    try:
        return stripe.Webhook.construct_event(payload, signature, secret)
    except stripe.SignatureVerificationError as exc:
        raise StripeServiceError("Invalid Stripe webhook signature") from exc
    except ValueError as exc:
        raise StripeServiceError("Invalid Stripe webhook payload") from exc


async def record_platform_billing_webhook_once(
    db: AsyncSession,
    event: Any,
) -> WebhookRecordResult:
    event_id = str(getattr(event, "id", "") or "")
    event_type = str(getattr(event, "type", "") or "")
    if not event_id or not event_type:
        raise StripeServiceError("Stripe webhook event missing id or type")

    existing = (
        await db.execute(
            select(PlatformBillingWebhookEvent).where(
                PlatformBillingWebhookEvent.stripe_event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return WebhookRecordResult(
            event=existing,
            duplicate=True,
            already_processed=existing.processed_at is not None,
        )

    row = PlatformBillingWebhookEvent(
        stripe_event_id=event_id,
        event_type=event_type,
        payload_json=_stripe_object_to_dict(event),
        processed_at=None,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        existing = (
            await db.execute(
                select(PlatformBillingWebhookEvent).where(
                    PlatformBillingWebhookEvent.stripe_event_id == event_id
                )
            )
        ).scalar_one()
        return WebhookRecordResult(
            event=existing,
            duplicate=True,
            already_processed=existing.processed_at is not None,
        )
    return WebhookRecordResult(event=row, duplicate=False, already_processed=False)


async def _unique_slug(session: AsyncSession, base: str) -> str:
    slug = base
    suffix = 1
    while True:
        existing = (
            await session.execute(select(Tenant.id).where(Tenant.slug == slug))
        ).scalar_one_or_none()
        if existing is None:
            return slug
        suffix += 1
        slug = f"{base[:90]}-{suffix}"


async def _create_self_serve_tenant(
    session: AsyncSession,
    *,
    organisation_name: str,
    country: str,
    industry: str | None,
    plan: str,
    slug: str | None = None,
) -> Tenant:
    resolved_slug = slug or await _unique_slug(session, _slugify_org(organisation_name))
    tenant = Tenant(
        name=organisation_name.strip(),
        slug=resolved_slug,
        is_active=True,
        is_platform=False,
        lifecycle_status="active",
        settings_json=build_tenant_settings(
            country=country,
            industry=industry,
            onboarding_completed=False,
        ),
    )
    session.add(tenant)
    await session.flush()
    await _seed_modules(session, tenant.id)
    await ensure_default_config(session, tenant.id)
    await ensure_tenant_billing(session, tenant.id, plan=plan)
    return tenant


async def _create_admin_user(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    email: str,
    password_hash: str,
    full_name: str | None,
) -> User:
    normalized_email = email.strip().lower()
    account = (
        await session.execute(
            select(AuthAccount).where(AuthAccount.email.ilike(normalized_email))
        )
    ).scalar_one_or_none()
    if not account:
        account = AuthAccount(email=normalized_email, password_hash=password_hash)
        session.add(account)
        await session.flush()
    else:
        account.password_hash = password_hash

    display_name = (full_name or "").strip() or normalized_email.split("@")[0]
    user = User(
        tenant_id=tenant_id,
        auth_account_id=account.id,
        email=normalized_email,
        password_hash=password_hash,
        full_name=display_name,
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    await ensure_membership(
        session,
        user_id=user.id,
        tenant_id=tenant_id,
        role=TenantRole.ADMIN.value,
    )
    return user


def _validate_signup_request(
    *,
    email: str,
    password: str,
    organisation_name: str,
    country: str,
    plan_code: str,
    signup_source: str,
    signup_token: str | None,
) -> None:
    if signup_source == SIGNUP_SOURCE_INVITE and not (signup_token or "").strip():
        raise HTTPException(400, "signup_token is required for invite signup")
    if signup_source == SIGNUP_SOURCE_PUBLIC and signup_token:
        raise HTTPException(400, "signup_token must not be sent for public signup")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not organisation_name.strip():
        raise HTTPException(400, "Organisation name is required")
    country_code = country.strip().upper()
    if len(country_code) != 2 or not country_code.isalpha():
        raise HTTPException(400, "Country must be a 2-letter code")
    pricing_region_for_country(country_code)
    normalized_plan = plan_code.strip().lower()
    if normalized_plan not in {PLAN_FREE, PLAN_STUDIO}:
        raise HTTPException(400, "Only Free or Studio signup is supported")
    if not str(email).strip():
        raise HTTPException(400, "Email is required")


def _plan_snapshot(country: str, plan_code: str) -> dict[str, Any]:
    region = pricing_region_for_country(country)
    normalized = plan_code.strip().lower()
    if normalized == PLAN_ENTERPRISE:
        raise HTTPException(400, "Enterprise plan requires contacting sales")
    if normalized not in {PLAN_FREE, PLAN_STUDIO}:
        raise HTTPException(400, "Unsupported plan")
    definition = plan_definition(country_code=country, plan=normalized)
    return {
        "region": region,
        "plan_code": normalized,
        "currency": region_currency(region),
        "monthly_credits": definition.monthly_credits,
        "user_limit": definition.max_users,
        "monthly_price": definition.monthly_price,
    }


async def complete_free_signup(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    organisation_name: str,
    country: str,
    industry: str | None = None,
    full_name: str | None = None,
    signup_source: str = SIGNUP_SOURCE_PUBLIC,
    signup_token: str | None = None,
) -> SignupFreeResult:
    _validate_signup_request(
        email=email,
        password=password,
        organisation_name=organisation_name,
        country=country,
        plan_code=PLAN_FREE,
        signup_source=signup_source,
        signup_token=signup_token,
    )

    snapshot = _plan_snapshot(country, PLAN_FREE)
    token = signup_token or secrets.token_urlsafe(32)

    await apply_platform_lookup_session(session)
    try:
        tenant = await _create_self_serve_tenant(
            session,
            organisation_name=organisation_name,
            country=country,
            industry=industry,
            plan=PLAN_FREE,
        )
        billing = await session.get(TenantBilling, tenant.id)
        if billing:
            billing.billing_country = snapshot["region"]
            billing.billing_currency = snapshot["currency"]
            billing.monthly_credits = snapshot["monthly_credits"]
            billing.user_limit = snapshot["user_limit"]

        pending = PendingSignupBillingSession(
            signup_token=token,
            email=email.strip().lower(),
            organisation_name=organisation_name.strip(),
            organisation_slug=tenant.slug,
            country=country.strip().upper(),
            plan_code=PLAN_FREE,
            currency=snapshot["currency"],
            monthly_credits=snapshot["monthly_credits"],
            user_limit=snapshot["user_limit"],
            password_hash=hash_password(password),
            full_name=full_name,
            industry=industry,
            tenant_id=tenant.id,
            status=SIGNUP_STATUS_COMPLETED,
            signup_source=signup_source,
            completed_at=_utc_now(),
        )
        session.add(pending)
        await apply_rls_session_context(session, tenant.id)
        await _create_admin_user(
            session,
            tenant_id=tenant.id,
            email=email,
            password_hash=pending.password_hash or "",
            full_name=full_name,
        )
        await session.flush()
        return SignupFreeResult(tenant_id=tenant.id, signup_token=token)
    finally:
        await clear_platform_lookup_session(session)


async def create_signup_checkout_session(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    organisation_name: str,
    country: str,
    plan_code: str,
    industry: str | None = None,
    full_name: str | None = None,
    signup_token: str | None = None,
    signup_source: str = SIGNUP_SOURCE_PUBLIC,
) -> CheckoutSessionResult | SignupFreeResult:
    normalized_plan = plan_code.strip().lower()
    _validate_signup_request(
        email=email,
        password=password,
        organisation_name=organisation_name,
        country=country,
        plan_code=normalized_plan,
        signup_source=signup_source,
        signup_token=signup_token,
    )

    if normalized_plan == PLAN_FREE:
        return await complete_free_signup(
            session,
            email=email,
            password=password,
            organisation_name=organisation_name,
            country=country,
            industry=industry,
            full_name=full_name,
            signup_source=signup_source,
            signup_token=signup_token,
        )
    if normalized_plan != PLAN_STUDIO:
        raise HTTPException(400, "Only Free or Studio signup is supported")

    cfg = _require_platform_billing()
    snapshot = _plan_snapshot(country, PLAN_STUDIO)
    region = snapshot["region"]
    price_id = cfg.stripe_studio_price_id_for_region(region)
    if not price_id:
        raise HTTPException(503, f"Studio price is not configured for region {region}")

    token = signup_token or secrets.token_urlsafe(32)

    await apply_platform_lookup_session(session)
    try:
        slug = await _unique_slug(session, _slugify_org(organisation_name))
        pending = PendingSignupBillingSession(
            id=uuid.uuid4(),
            signup_token=token,
            email=email.strip().lower(),
            organisation_name=organisation_name.strip(),
            organisation_slug=slug,
            country=country.strip().upper(),
            plan_code=PLAN_STUDIO,
            currency=snapshot["currency"],
            monthly_credits=int(snapshot["monthly_credits"]),
            user_limit=int(snapshot["user_limit"]),
            password_hash=hash_password(password),
            full_name=full_name,
            industry=industry,
            status=SIGNUP_STATUS_PENDING,
            signup_source=signup_source,
        )
        session.add(pending)
        await session.flush()

        success_url = _checkout_return_url(
            build_public_app_path("/signup?checkout=success")
        )
        cancel_url = build_public_app_path("/signup?checkout=cancelled")

        checkout = await _run_stripe(
            stripe.checkout.Session.create,
            mode="subscription",
            customer_email=pending.email,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "pending_signup_id": str(pending.id),
                "signup_token": token,
                "email": pending.email,
                "organisation_name": pending.organisation_name,
                "country": pending.country,
                "plan_code": PLAN_STUDIO,
                "currency": pending.currency,
                "monthly_credits": str(pending.monthly_credits),
                "user_limit": str(pending.user_limit),
                "event_type": "signup_subscription",
                "signup_source": signup_source,
            },
            subscription_data={
                "metadata": {
                    "pending_signup_id": str(pending.id),
                    "plan_code": PLAN_STUDIO,
                }
            },
        )
        pending.stripe_checkout_session_id = str(checkout.get("id") or "")
        await session.flush()
        return CheckoutSessionResult(
            checkout_url=str(checkout.get("url") or ""),
            session_id=pending.stripe_checkout_session_id,
            status=SIGNUP_STATUS_PENDING,
            pending_signup_id=str(pending.id),
        )
    finally:
        await clear_platform_lookup_session(session)


async def create_topup_checkout_session(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
    user_email: str,
    amount: Decimal,
) -> CheckoutSessionResult:
    cfg = _require_platform_billing()
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    billing = await refresh_tenant_billing(session, tenant_id)
    if billing.plan == PLAN_ENTERPRISE:
        raise HTTPException(400, "Enterprise top-up is managed by your account team")

    region = tenant_pricing_region(tenant)
    currency = region_currency(region).lower()
    settings = await get_platform_credit_settings(session)
    factor = getattr(settings, topup_factor_key(region))
    credits = int(amount * factor)
    if credits <= 0:
        raise HTTPException(400, "Top-up amount too small")

    amount_cents = int((amount * 100).to_integral_value())
    success_url = _checkout_return_url(cfg.stripe_platform_billing_success_url_resolved())
    cancel_url = cfg.stripe_platform_billing_cancel_url_resolved()

    checkout = await _run_stripe(
        stripe.checkout.Session.create,
        mode="payment",
        customer=billing.stripe_customer_id or None,
        customer_email=None if billing.stripe_customer_id else user_email.strip().lower(),
        line_items=[
            {
                "price_data": {
                    "currency": currency,
                    "unit_amount": amount_cents,
                    "product_data": {"name": "LedgerLink credit top-up"},
                },
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "event_type": EVENT_CREDIT_TOPUP,
            "amount": str(amount),
            "currency": currency.upper(),
            "credits_to_add": str(credits),
        },
    )
    return CheckoutSessionResult(
        checkout_url=str(checkout.get("url") or ""),
        session_id=str(checkout.get("id") or ""),
        status="pending",
        tenant_id=str(tenant_id),
    )


async def create_subscription_upgrade_checkout(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
    user_email: str,
) -> CheckoutSessionResult:
    cfg = _require_platform_billing()
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    billing = await refresh_tenant_billing(session, tenant_id)
    if billing.plan == PLAN_ENTERPRISE:
        raise HTTPException(400, "Enterprise plan is managed by sales")
    if billing.plan == PLAN_STUDIO:
        raise HTTPException(400, "Already on Studio plan")

    country = tenant_country(tenant)
    region = pricing_region_for_country(country)
    snapshot = _plan_snapshot(country, PLAN_STUDIO)
    price_id = cfg.stripe_studio_price_id_for_region(region)
    if not price_id:
        raise HTTPException(503, f"Studio price is not configured for region {region}")

    success_url = _checkout_return_url(cfg.stripe_platform_billing_success_url_resolved())
    cancel_url = cfg.stripe_platform_billing_cancel_url_resolved()

    checkout = await _run_stripe(
        stripe.checkout.Session.create,
        mode="subscription",
        customer=billing.stripe_customer_id or None,
        customer_email=None if billing.stripe_customer_id else user_email.strip().lower(),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "event_type": EVENT_PLAN_UPGRADE,
            "organisation_name": tenant.name,
            "country": country,
            "plan_code": PLAN_STUDIO,
            "currency": snapshot["currency"],
            "monthly_credits": str(snapshot["monthly_credits"]),
            "user_limit": str(snapshot["user_limit"]),
        },
        subscription_data={
            "metadata": {
                "tenant_id": str(tenant_id),
                "plan_code": PLAN_STUDIO,
            }
        },
    )
    return CheckoutSessionResult(
        checkout_url=str(checkout.get("url") or ""),
        session_id=str(checkout.get("id") or ""),
        status="pending",
        tenant_id=str(tenant_id),
    )


async def get_checkout_status(
    session: AsyncSession,
    *,
    session_id: str,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    cfg = get_settings()
    if not session_id.strip():
        raise HTTPException(400, "session_id is required")

    if cfg.stripe_platform_billing_active:
        try:
            checkout = await _run_stripe(stripe.checkout.Session.retrieve, session_id)
            meta = checkout.get("metadata") or {}
            if tenant_id is not None:
                meta_tid = meta.get("tenant_id")
                if meta_tid and str(tenant_id) != str(meta_tid):
                    raise HTTPException(403, "Checkout session does not belong to this tenant")
            return {
                "session_id": session_id,
                "status": checkout.get("status"),
                "payment_status": checkout.get("payment_status"),
                "mode": checkout.get("mode"),
                "event_type": meta.get("event_type"),
            }
        except stripe.StripeError as exc:
            raise HTTPException(400, "Unable to retrieve checkout session") from exc

    pending = (
        await session.execute(
            select(PendingSignupBillingSession).where(
                PendingSignupBillingSession.stripe_checkout_session_id == session_id
            )
        )
    ).scalar_one_or_none()
    if pending:
        return {
            "session_id": session_id,
            "status": pending.status,
            "payment_status": "paid" if pending.status == SIGNUP_STATUS_COMPLETED else "unpaid",
            "mode": "subscription",
            "event_type": "signup_subscription",
            "tenant_id": str(pending.tenant_id) if pending.tenant_id else None,
        }
    raise HTTPException(404, "Checkout session not found")


async def get_signup_checkout_status(
    session: AsyncSession,
    *,
    session_id: str,
) -> dict[str, Any]:
    await apply_platform_lookup_session(session)
    try:
        pending = (
            await session.execute(
                select(PendingSignupBillingSession).where(
                    PendingSignupBillingSession.stripe_checkout_session_id == session_id
                )
            )
        ).scalar_one_or_none()
        if pending:
            return {
                "session_id": session_id,
                "status": pending.status,
                "payment_status": "paid" if pending.status == SIGNUP_STATUS_COMPLETED else "unpaid",
                "tenant_id": str(pending.tenant_id) if pending.tenant_id else None,
                "email": pending.email,
            }
        return await get_checkout_status(session, session_id=session_id)
    finally:
        await clear_platform_lookup_session(session)


async def _activate_pending_signup_from_checkout(
    session: AsyncSession,
    *,
    pending: PendingSignupBillingSession,
    checkout_session: dict[str, Any],
    subscription: dict[str, Any] | None,
) -> uuid.UUID:
    if pending.status == SIGNUP_STATUS_COMPLETED and pending.tenant_id:
        return pending.tenant_id

    customer_id = str(checkout_session.get("customer") or pending.stripe_customer_id or "")
    subscription_id = str(
        (subscription or {}).get("id")
        or checkout_session.get("subscription")
        or pending.stripe_subscription_id
        or ""
    )
    price_id = ""
    if subscription:
        items = (subscription.get("items") or {}).get("data") or []
        if items:
            price_id = str((items[0].get("price") or {}).get("id") or "")

    tenant = await _create_self_serve_tenant(
        session,
        organisation_name=pending.organisation_name,
        country=pending.country,
        industry=pending.industry,
        plan=PLAN_FREE,
        slug=pending.organisation_slug,
    )
    await apply_rls_session_context(session, tenant.id)
    await _create_admin_user(
        session,
        tenant_id=tenant.id,
        email=pending.email,
        password_hash=pending.password_hash or "",
        full_name=pending.full_name,
    )
    await apply_studio_subscription_to_billing(
        session,
        tenant.id,
        country_code=pending.country,
        stripe_customer_id=customer_id or None,
        stripe_subscription_id=subscription_id or None,
        stripe_price_id=price_id or None,
        subscription_status=(subscription or {}).get("status"),
        current_period_start=_unix_to_dt((subscription or {}).get("current_period_start")),
        current_period_end=_unix_to_dt((subscription or {}).get("current_period_end")),
        cancel_at_period_end=bool((subscription or {}).get("cancel_at_period_end")),
        grant_initial_credits=True,
        idempotency_key=f"signup_subscription:{checkout_session.get('id')}",
        stripe_checkout_session_id=str(checkout_session.get("id") or ""),
    )

    pending.tenant_id = tenant.id
    pending.status = SIGNUP_STATUS_COMPLETED
    pending.completed_at = _utc_now()
    pending.stripe_customer_id = customer_id or None
    pending.stripe_subscription_id = subscription_id or None
    await session.flush()
    return tenant.id


async def _sync_subscription_to_billing(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subscription: dict[str, Any],
) -> None:
    billing = await session.get(TenantBilling, tenant_id)
    if not billing:
        return

    items = (subscription.get("items") or {}).get("data") or []
    price_id = ""
    if items:
        price_id = str((items[0].get("price") or {}).get("id") or "")

    billing.stripe_subscription_id = str(subscription.get("id") or billing.stripe_subscription_id or "")
    billing.stripe_customer_id = str(subscription.get("customer") or billing.stripe_customer_id or "")
    billing.stripe_price_id = price_id or billing.stripe_price_id
    billing.subscription_status = str(subscription.get("status") or billing.subscription_status or "")
    billing.current_period_start = _unix_to_dt(subscription.get("current_period_start"))
    billing.current_period_end = _unix_to_dt(subscription.get("current_period_end"))
    billing.cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
    await session.flush()


async def _handle_checkout_completed(session: AsyncSession, event_obj: dict[str, Any]) -> None:
    checkout = event_obj.get("data", {}).get("object") or {}
    if checkout.get("payment_status") not in {"paid", "no_payment_required"}:
        return

    session_id = str(checkout.get("id") or "")
    mode = str(checkout.get("mode") or "")
    metadata = checkout.get("metadata") or {}

    if mode == "payment" and metadata.get("event_type") == EVENT_CREDIT_TOPUP:
        tenant_id = uuid.UUID(str(metadata["tenant_id"]))
        credits = int(metadata.get("credits_to_add") or 0)
        amount = Decimal(str(metadata.get("amount") or "0"))
        currency = str(metadata.get("currency") or "").upper()
        await apply_rls_session_context(session, tenant_id)
        await grant_credits_idempotent(
            session,
            tenant_id,
            credits=credits,
            idempotency_key=f"topup:{session_id}",
            event_type="top_up",
            description=f"Credit top-up ({currency} {amount})",
            amount_paid=amount,
            currency_code=currency,
            stripe_checkout_session_id=session_id,
            stripe_payment_intent_id=str(checkout.get("payment_intent") or "") or None,
        )
        return

    if mode == "subscription":
        pending_id = metadata.get("pending_signup_id")
        if pending_id:
            await apply_platform_lookup_session(session)
            try:
                pending = await session.get(PendingSignupBillingSession, uuid.UUID(str(pending_id)))
                if not pending:
                    return
                subscription_id = str(checkout.get("subscription") or "")
                subscription = None
                if subscription_id:
                    subscription = _stripe_object_to_dict(
                        await _run_stripe(stripe.Subscription.retrieve, subscription_id)
                    )
                await _activate_pending_signup_from_checkout(
                    session,
                    pending=pending,
                    checkout_session=checkout,
                    subscription=subscription,
                )
            finally:
                await clear_platform_lookup_session(session)
            return

        tenant_id_raw = metadata.get("tenant_id")
        if tenant_id_raw and metadata.get("event_type") == EVENT_PLAN_UPGRADE:
            tenant_id = uuid.UUID(str(tenant_id_raw))
            tenant = await session.get(Tenant, tenant_id)
            subscription_id = str(checkout.get("subscription") or "")
            subscription = None
            if subscription_id:
                subscription = _stripe_object_to_dict(
                    await _run_stripe(stripe.Subscription.retrieve, subscription_id)
                )
            await apply_rls_session_context(session, tenant_id)
            await apply_studio_subscription_to_billing(
                session,
                tenant_id,
                country_code=tenant_country(tenant) if tenant else metadata.get("country"),
                stripe_customer_id=str(checkout.get("customer") or "") or None,
                stripe_subscription_id=subscription_id or None,
                stripe_price_id=str(
                    ((subscription or {}).get("items") or {}).get("data", [{}])[0]
                    .get("price", {})
                    .get("id")
                    or ""
                )
                or None,
                subscription_status=(subscription or {}).get("status"),
                current_period_start=_unix_to_dt((subscription or {}).get("current_period_start")),
                current_period_end=_unix_to_dt((subscription or {}).get("current_period_end")),
                grant_initial_credits=True,
                idempotency_key=f"signup_subscription:{session_id}",
                stripe_checkout_session_id=session_id,
            )


async def _handle_checkout_expired(session: AsyncSession, event_obj: dict[str, Any]) -> None:
    checkout = event_obj.get("data", {}).get("object") or {}
    session_id = str(checkout.get("id") or "")
    if not session_id:
        return
    await apply_platform_lookup_session(session)
    try:
        pending = (
            await session.execute(
                select(PendingSignupBillingSession).where(
                    PendingSignupBillingSession.stripe_checkout_session_id == session_id,
                    PendingSignupBillingSession.status == SIGNUP_STATUS_PENDING,
                )
            )
        ).scalar_one_or_none()
        if pending:
            pending.status = SIGNUP_STATUS_EXPIRED
            await session.flush()
    finally:
        await clear_platform_lookup_session(session)


async def _handle_invoice_paid(session: AsyncSession, event_obj: dict[str, Any]) -> None:
    invoice = event_obj.get("data", {}).get("object") or {}
    invoice_id = str(invoice.get("id") or "")
    if not invoice_id:
        return

    billing_reason = str(invoice.get("billing_reason") or "")
    if billing_reason == "subscription_create":
        return

    subscription_id = str(invoice.get("subscription") or "")
    if not subscription_id:
        return

    billing = (
        await session.execute(
            select(TenantBilling).where(TenantBilling.stripe_subscription_id == subscription_id)
        )
    ).scalar_one_or_none()
    if not billing:
        return

    tenant = await session.get(Tenant, billing.tenant_id)
    credits = billing.monthly_credits or monthly_credits_for_plan(
        country_code=tenant_country(tenant),
        plan=PLAN_STUDIO,
    )
    if credits <= 0:
        return

    period_start = _unix_to_dt(invoice.get("period_start"))
    period_end = _unix_to_dt(invoice.get("period_end"))
    billing.subscription_status = "active"
    if period_start:
        billing.current_period_start = period_start
    if period_end:
        billing.current_period_end = period_end

    await apply_rls_session_context(session, billing.tenant_id)
    await grant_credits_idempotent(
        session,
        billing.tenant_id,
        credits=credits,
        idempotency_key=f"monthly_credits:{invoice_id}",
        event_type="monthly_grant",
        description="Studio subscription renewal — monthly credits",
        amount_paid=Decimal(str((invoice.get("amount_paid") or 0))) / Decimal("100"),
        currency_code=str(invoice.get("currency") or billing.billing_currency or "").upper() or None,
        stripe_invoice_id=invoice_id,
    )
    billing.last_monthly_grant_at = date.today()
    await session.flush()


async def _handle_invoice_payment_failed(session: AsyncSession, event_obj: dict[str, Any]) -> None:
    invoice = event_obj.get("data", {}).get("object") or {}
    subscription_id = str(invoice.get("subscription") or "")
    if not subscription_id:
        return
    billing = (
        await session.execute(
            select(TenantBilling).where(TenantBilling.stripe_subscription_id == subscription_id)
        )
    ).scalar_one_or_none()
    if billing:
        billing.subscription_status = "past_due"
        await session.flush()


async def _handle_subscription_event(session: AsyncSession, event_obj: dict[str, Any]) -> None:
    subscription = event_obj.get("data", {}).get("object") or {}
    subscription_id = str(subscription.get("id") or "")
    if not subscription_id:
        return

    billing = (
        await session.execute(
            select(TenantBilling).where(TenantBilling.stripe_subscription_id == subscription_id)
        )
    ).scalar_one_or_none()
    if not billing:
        meta = subscription.get("metadata") or {}
        tenant_raw = meta.get("tenant_id")
        if tenant_raw:
            billing = await session.get(TenantBilling, uuid.UUID(str(tenant_raw)))
    if not billing:
        return

    await apply_rls_session_context(session, billing.tenant_id)
    await _sync_subscription_to_billing(session, tenant_id=billing.tenant_id, subscription=subscription)
    event_type = str(event_obj.get("type") or "")
    if event_type == "customer.subscription.deleted":
        billing.subscription_status = "canceled"
        billing.plan = PLAN_FREE
        await session.flush()


def monthly_credits_for_plan(*, country_code: str | None, plan: str) -> int:
    from app.services.credit_catalog import monthly_credits_for_plan as _monthly

    return _monthly(country_code=country_code, plan=plan)


async def process_platform_billing_webhook_event(
    session: AsyncSession,
    event: Any,
    *,
    webhook_row: PlatformBillingWebhookEvent,
) -> None:
    event_type = str(getattr(event, "type", "") or "")
    payload = _stripe_object_to_dict(event)

    handlers = {
        "checkout.session.completed": _handle_checkout_completed,
        "checkout.session.expired": _handle_checkout_expired,
        "invoice.paid": _handle_invoice_paid,
        "invoice.payment_failed": _handle_invoice_payment_failed,
        "customer.subscription.created": _handle_subscription_event,
        "customer.subscription.updated": _handle_subscription_event,
        "customer.subscription.deleted": _handle_subscription_event,
        "payment_intent.succeeded": lambda _s, _e: None,
        "payment_intent.payment_failed": lambda _s, _e: None,
    }
    handler = handlers.get(event_type)
    if handler:
        await handler(session, payload)
    webhook_row.processed_at = _utc_now()
    await session.flush()


def public_plans_for_country(country: str | None) -> list[dict[str, object]]:
    return list_country_plans(country_code=country)
