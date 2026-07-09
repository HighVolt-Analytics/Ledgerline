"""Tenant credits: plans, deductions, top-up, rollover, and ledger."""

from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_ledger import CreditLedgerEntry
from app.models.platform_credit_settings import PlatformCreditSettings
from app.models.tenant import Tenant
from app.models.tenant_billing import TenantBilling
from app.services.azure_usage_cost import estimate_upload_azure_cost
from app.services.credit_catalog import (
    FY_DAYS,
    PLAN_ENTERPRISE,
    PLAN_FREE,
    PLAN_STUDIO,
    monthly_credits_for_plan,
    plan_definition,
    pricing_region_for_country,
    region_currency,
    tenant_pricing_region,
    topup_factor_key,
)
from app.services.extraction.document_ai_provider import DocumentAiProvider
from app.tenant_settings import tenant_country


class InsufficientCreditsError(Exception):
    def __init__(self, balance: int, required: int) -> None:
        self.balance = balance
        self.required = required
        super().__init__(f"Insufficient credits: need {required}, balance {balance}")


class PlanFeatureBlockedError(Exception):
    def __init__(self, feature: str, message: str) -> None:
        self.feature = feature
        super().__init__(message)


class SeatLimitError(Exception):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"User seat limit reached ({limit}). Upgrade to Studio for more seats.")


async def get_platform_credit_settings(session: AsyncSession) -> PlatformCreditSettings:
    row = await session.get(PlatformCreditSettings, 1)
    if row is None:
        row = PlatformCreditSettings(id=1)
        session.add(row)
        await session.flush()
    return row


async def update_platform_credit_settings(
    session: AsyncSession,
    *,
    credits_per_page: int | None = None,
    universal_credits_per_page: bool | None = None,
    topup_factor_in: Decimal | None = None,
    topup_factor_sg: Decimal | None = None,
    topup_factor_au: Decimal | None = None,
) -> PlatformCreditSettings:
    settings = await get_platform_credit_settings(session)
    if credits_per_page is not None:
        settings.credits_per_page = max(1, int(credits_per_page))
    if universal_credits_per_page is not None:
        settings.universal_credits_per_page = bool(universal_credits_per_page)
    if topup_factor_in is not None:
        settings.topup_factor_in = Decimal(str(topup_factor_in))
    if topup_factor_sg is not None:
        settings.topup_factor_sg = Decimal(str(topup_factor_sg))
    if topup_factor_au is not None:
        settings.topup_factor_au = Decimal(str(topup_factor_au))
    await session.flush()
    return settings


def _add_months(anchor: date, months: int) -> date:
    month_index = anchor.month - 1 + months
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _next_monthly_grant_date(billing: TenantBilling) -> date:
    if billing.last_monthly_grant_at is None:
        return billing.billing_anchor_date
    return _add_months(billing.billing_anchor_date, _months_between(billing.billing_anchor_date, billing.last_monthly_grant_at) + 1)


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


async def ensure_tenant_billing(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    plan: str | None = None,
) -> TenantBilling:
    billing = await session.get(TenantBilling, tenant_id)
    if billing is not None:
        return billing

    tenant = await session.get(Tenant, tenant_id)
    today = date.today()
    initial_plan = plan or PLAN_FREE
    region = tenant_pricing_region(tenant) if tenant else pricing_region_for_country(None)
    credits = monthly_credits_for_plan(
        country_code=tenant_country(tenant) if tenant else None,
        plan=initial_plan,
    )
    billing = TenantBilling(
        tenant_id=tenant_id,
        plan=initial_plan,
        credit_balance=credits,
        billing_anchor_date=today,
        last_monthly_grant_at=today if credits > 0 else None,
    )
    session.add(billing)
    await session.flush()

    if credits > 0:
        session.add(
            CreditLedgerEntry(
                tenant_id=tenant_id,
                event_type="monthly_grant",
                description="Initial plan credits",
                credits_delta=credits,
                balance_after=credits,
                plan_at_event=initial_plan,
            )
        )
        await session.flush()
    return billing


async def _apply_billing_period_rules(
    session: AsyncSession,
    billing: TenantBilling,
    tenant: Tenant | None,
) -> None:
    today = date.today()
    country = tenant_country(tenant) if tenant else None
    fy_end = billing.billing_anchor_date + timedelta(days=FY_DAYS)

    if today >= fy_end:
        if billing.credit_balance > 0:
            expired = billing.credit_balance
            billing.credit_balance = 0
            session.add(
                CreditLedgerEntry(
                    tenant_id=billing.tenant_id,
                    event_type="fy_expiry",
                    description="Financial year end — all unused credits expired",
                    credits_delta=-expired,
                    balance_after=0,
                    plan_at_event=billing.plan,
                )
            )
        billing.billing_anchor_date = today
        billing.last_monthly_grant_at = None

    grant_amount = monthly_credits_for_plan(
        country_code=country,
        plan=billing.plan,
        enterprise_monthly_credits=billing.enterprise_monthly_credits,
    )
    next_grant = _next_monthly_grant_date(billing)
    while grant_amount > 0 and next_grant <= today:
        billing.credit_balance += grant_amount
        billing.last_monthly_grant_at = next_grant
        session.add(
            CreditLedgerEntry(
                tenant_id=billing.tenant_id,
                event_type="monthly_grant",
                description=f"Monthly {billing.plan} plan credits",
                credits_delta=grant_amount,
                balance_after=billing.credit_balance,
                plan_at_event=billing.plan,
            )
        )
        next_grant = _add_months(billing.billing_anchor_date, _months_between(billing.billing_anchor_date, billing.last_monthly_grant_at) + 1)

    await session.flush()


async def get_credits_per_page(
    session: AsyncSession,
    billing: TenantBilling,
) -> int:
    settings = await get_platform_credit_settings(session)
    if settings.universal_credits_per_page:
        return max(1, settings.credits_per_page)
    if billing.credits_per_page_override is not None:
        return max(1, billing.credits_per_page_override)
    return max(1, settings.credits_per_page)


async def refresh_tenant_billing(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> TenantBilling:
    tenant = await session.get(Tenant, tenant_id)
    billing = await ensure_tenant_billing(session, tenant_id)
    await _apply_billing_period_rules(session, billing, tenant)
    return billing


async def get_tenant_plan_features(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    tenant = await session.get(Tenant, tenant_id)
    billing = await refresh_tenant_billing(session, tenant_id)
    plan_def = plan_definition(country_code=tenant_country(tenant), plan=billing.plan)
    studio_def = plan_definition(country_code=tenant_country(tenant), plan=PLAN_STUDIO)
    cpp = await get_credits_per_page(session, billing)
    region = tenant_pricing_region(tenant) if tenant else pricing_region_for_country(None)
    settings = await get_platform_credit_settings(session)
    factor = getattr(settings, topup_factor_key(region))
    return {
        "plan": billing.plan,
        "region": region,
        "currency_code": region_currency(region),
        "credit_balance": billing.credit_balance,
        "credits_per_page": cpp,
        "monthly_credits": monthly_credits_for_plan(
            country_code=tenant_country(tenant),
            plan=billing.plan,
            enterprise_monthly_credits=billing.enterprise_monthly_credits,
        ),
        "max_users": plan_def.max_users,
        "social_integration": plan_def.social_integration,
        "email_integration": plan_def.email_integration,
        "studio_monthly_price": float(studio_def.monthly_price),
        "topup_factor": float(factor),
    }


async def assert_can_ingest_via_channel(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    channel: str,
) -> None:
    features = await get_tenant_plan_features(session, tenant_id)
    if channel in {"whatsapp", "viber", "social"} and not features["social_integration"]:
        raise PlanFeatureBlockedError(
            "social_integration",
            "Social channel ingest requires Studio or Enterprise. Upgrade your plan.",
        )
    if channel in {"email", "mailbox"} and not features["email_integration"]:
        raise PlanFeatureBlockedError(
            "email_integration",
            "Email ingest requires Studio or Enterprise. Upgrade your plan.",
        )


async def assert_can_upload(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    pages: int,
) -> int:
    """Return credits required; raise if insufficient."""
    billing = await refresh_tenant_billing(session, tenant_id)
    cpp = await get_credits_per_page(session, billing)
    required = max(1, pages) * cpp
    if billing.credit_balance < required:
        raise InsufficientCreditsError(billing.credit_balance, required)
    return required


async def charge_upload_credits(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    pages: int,
    idempotency_key: str,
    invoice_id: int | None = None,
    filename: str | None = None,
    document_ai_provider: str | None = None,
) -> CreditLedgerEntry | None:
    """Deduct credits once per document (idempotent by key)."""
    existing = (
        await session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.tenant_id == tenant_id,
                CreditLedgerEntry.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    billing = await refresh_tenant_billing(session, tenant_id)
    cpp = await get_credits_per_page(session, billing)
    page_count = max(1, pages)
    required = page_count * cpp
    if billing.credit_balance < required:
        raise InsufficientCreditsError(billing.credit_balance, required)

    settings = await get_platform_credit_settings(session)
    provider = DocumentAiProvider.from_config(document_ai_provider)
    azure = estimate_upload_azure_cost(pages=page_count, provider=provider, settings=settings)

    billing.credit_balance -= required
    entry = CreditLedgerEntry(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        event_type="upload_charge",
        description=f"Document processed ({page_count} page{'s' if page_count != 1 else ''})",
        pages=page_count,
        credits_per_page=cpp,
        credits_delta=-required,
        balance_after=billing.credit_balance,
        plan_at_event=billing.plan,
        idempotency_key=idempotency_key,
        filename=filename,
        azure_cost_usd=azure.total_usd,
        azure_cost_breakdown_json=azure.breakdown,
    )
    session.add(entry)
    await session.flush()
    return entry


async def grant_credits_idempotent(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    credits: int,
    idempotency_key: str,
    event_type: str,
    description: str,
    amount_paid: Decimal | None = None,
    currency_code: str | None = None,
    stripe_checkout_session_id: str | None = None,
    stripe_payment_intent_id: str | None = None,
    stripe_invoice_id: str | None = None,
) -> CreditLedgerEntry | None:
    """Grant credits once per idempotency key."""
    if credits <= 0:
        return None

    existing = (
        await session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.tenant_id == tenant_id,
                CreditLedgerEntry.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    billing = await refresh_tenant_billing(session, tenant_id)
    billing.credit_balance += credits
    entry = CreditLedgerEntry(
        tenant_id=tenant_id,
        event_type=event_type,
        description=description,
        credits_delta=credits,
        balance_after=billing.credit_balance,
        plan_at_event=billing.plan,
        idempotency_key=idempotency_key,
        amount_paid=amount_paid,
        currency_code=currency_code,
        stripe_checkout_session_id=stripe_checkout_session_id,
        stripe_payment_intent_id=stripe_payment_intent_id,
        stripe_invoice_id=stripe_invoice_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def apply_studio_subscription_to_billing(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    country_code: str | None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    stripe_price_id: str | None = None,
    subscription_status: str | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
    grant_initial_credits: bool = True,
    idempotency_key: str | None = None,
    stripe_checkout_session_id: str | None = None,
    stripe_invoice_id: str | None = None,
) -> TenantBilling:
    """Activate Studio plan and optionally grant the first monthly allowance."""
    from datetime import datetime as dt

    tenant = await session.get(Tenant, tenant_id)
    billing = await refresh_tenant_billing(session, tenant_id)
    region = pricing_region_for_country(country_code or tenant_country(tenant))
    studio_def = plan_definition(country_code=country_code or tenant_country(tenant), plan=PLAN_STUDIO)
    old_balance = billing.credit_balance

    billing.plan = PLAN_STUDIO
    billing.billing_country = region
    billing.billing_currency = region_currency(region)
    billing.monthly_credits = studio_def.monthly_credits
    billing.user_limit = studio_def.max_users
    if stripe_customer_id:
        billing.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        billing.stripe_subscription_id = stripe_subscription_id
    if stripe_price_id:
        billing.stripe_price_id = stripe_price_id
    if subscription_status:
        billing.subscription_status = subscription_status
    if current_period_start:
        billing.current_period_start = current_period_start
    if current_period_end:
        billing.current_period_end = current_period_end
    billing.cancel_at_period_end = cancel_at_period_end

    if grant_initial_credits:
        credits = studio_def.monthly_credits
        delta = credits - old_balance
        billing.credit_balance = credits
        billing.last_monthly_grant_at = date.today()
        key = idempotency_key or f"studio_activation:{tenant_id}"
        if delta != 0:
            await grant_credits_idempotent(
                session,
                tenant_id,
                credits=delta,
                idempotency_key=key,
                event_type="subscription_signup",
                description="Studio subscription activated — monthly allowance applied",
                amount_paid=studio_def.monthly_price,
                currency_code=region_currency(region),
                stripe_checkout_session_id=stripe_checkout_session_id,
                stripe_invoice_id=stripe_invoice_id,
            )
        else:
            existing = (
                await session.execute(
                    select(CreditLedgerEntry).where(
                        CreditLedgerEntry.tenant_id == tenant_id,
                        CreditLedgerEntry.idempotency_key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    CreditLedgerEntry(
                        tenant_id=tenant_id,
                        event_type="subscription_signup",
                        description="Studio subscription activated — monthly allowance applied",
                        credits_delta=0,
                        balance_after=billing.credit_balance,
                        plan_at_event=PLAN_STUDIO,
                        idempotency_key=key,
                        amount_paid=studio_def.monthly_price,
                        currency_code=region_currency(region),
                        stripe_checkout_session_id=stripe_checkout_session_id,
                        stripe_invoice_id=stripe_invoice_id,
                    )
                )
    await session.flush()
    return billing


async def top_up_credits(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    amount: Decimal,
) -> CreditLedgerEntry:
    tenant = await session.get(Tenant, tenant_id)
    billing = await refresh_tenant_billing(session, tenant_id)
    region = tenant_pricing_region(tenant) if tenant else pricing_region_for_country(None)
    settings = await get_platform_credit_settings(session)
    factor = getattr(settings, topup_factor_key(region))
    credits = int(amount * factor)
    if credits <= 0:
        raise ValueError("Top-up amount too small")

    billing.credit_balance += credits
    entry = CreditLedgerEntry(
        tenant_id=tenant_id,
        event_type="top_up",
        description=f"Credit top-up ({region_currency(region)} {amount})",
        credits_delta=credits,
        balance_after=billing.credit_balance,
        plan_at_event=billing.plan,
        amount_paid=amount,
        currency_code=region_currency(region),
    )
    session.add(entry)
    await session.flush()
    return entry


async def upgrade_to_studio(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> TenantBilling:
    tenant = await session.get(Tenant, tenant_id)
    billing = await refresh_tenant_billing(session, tenant_id)
    if billing.plan == PLAN_ENTERPRISE:
        raise ValueError("Enterprise plan is managed by sales")

    old_balance = billing.credit_balance
    billing.plan = PLAN_STUDIO
    studio_credits = monthly_credits_for_plan(
        country_code=tenant_country(tenant),
        plan=PLAN_STUDIO,
    )
    billing.credit_balance = studio_credits
    billing.last_monthly_grant_at = date.today()

    session.add(
        CreditLedgerEntry(
            tenant_id=tenant_id,
            event_type="plan_upgrade",
            description="Upgraded to Studio — monthly allowance applied",
            credits_delta=studio_credits - old_balance,
            balance_after=billing.credit_balance,
            plan_at_event=PLAN_STUDIO,
        )
    )
    await session.flush()
    return billing


async def set_tenant_plan(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    plan: str | None = None,
    enterprise_monthly_credits: int | None = None,
    credits_per_page_override: int | None = None,
    grant_credits: int | None = None,
) -> TenantBilling:
    tenant = await session.get(Tenant, tenant_id)
    billing = await refresh_tenant_billing(session, tenant_id)
    if plan is not None:
        normalized = plan.strip().lower()
        billing.plan = normalized
    else:
        normalized = billing.plan

    if enterprise_monthly_credits is not None:
        billing.enterprise_monthly_credits = enterprise_monthly_credits
    if credits_per_page_override is not None:
        billing.credits_per_page_override = credits_per_page_override

    if grant_credits is not None:
        billing.credit_balance += grant_credits
        session.add(
            CreditLedgerEntry(
                tenant_id=tenant_id,
                event_type="admin_grant",
                description="Super admin credit adjustment",
                credits_delta=grant_credits,
                balance_after=billing.credit_balance,
                plan_at_event=normalized,
            )
        )
    elif plan is not None and normalized == PLAN_STUDIO and billing.credit_balance == 0:
        credits = monthly_credits_for_plan(country_code=tenant_country(tenant), plan=PLAN_STUDIO)
        billing.credit_balance = credits
        billing.last_monthly_grant_at = date.today()
        session.add(
            CreditLedgerEntry(
                tenant_id=tenant_id,
                event_type="plan_change",
                description=f"Plan set to {normalized}",
                credits_delta=credits,
                balance_after=billing.credit_balance,
                plan_at_event=normalized,
            )
        )
    await session.flush()
    return billing


async def list_credit_ledger(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CreditLedgerEntry], int]:
    total = (
        await session.execute(
            select(func.count())
            .select_from(CreditLedgerEntry)
            .where(CreditLedgerEntry.tenant_id == tenant_id)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(CreditLedgerEntry)
            .where(CreditLedgerEntry.tenant_id == tenant_id)
            .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return list(rows), int(total)


async def tenant_azure_cost_total_usd(session: AsyncSession, tenant_id: uuid.UUID) -> Decimal:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedgerEntry.azure_cost_usd), 0)).where(
                CreditLedgerEntry.tenant_id == tenant_id,
                CreditLedgerEntry.azure_cost_usd.is_not(None),
            )
        )
    ).scalar_one()
    return Decimal(str(total))


async def tenant_credits_consumed(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(-CreditLedgerEntry.credits_delta), 0)).where(
                CreditLedgerEntry.tenant_id == tenant_id,
                CreditLedgerEntry.credits_delta < 0,
            )
        )
    ).scalar_one()
    return int(total)


async def assert_seat_available(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    from app.services.tenant.tenant_members_service import count_active_seats

    tenant = await session.get(Tenant, tenant_id)
    billing = await refresh_tenant_billing(session, tenant_id)
    plan_def = plan_definition(country_code=tenant_country(tenant), plan=billing.plan)
    seats = await count_active_seats(session, tenant_id)
    if seats >= plan_def.max_users:
        raise SeatLimitError(plan_def.max_users)
