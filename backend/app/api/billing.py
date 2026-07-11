"""Tenant billing credits API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _mint_session_tokens, _user_response
from app.api.deps import AuthContext, get_auth_context, get_db
from app.config import get_settings
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.billing import (
    BillingPlanCatalogItem,
    BillingPlansResponse,
    BillingSignupCheckoutRequest,
    BillingStateResponse,
    BillingTopUpCheckoutRequest,
    BillingTopUpRequest,
    BillingUpgradeRequest,
    BillingUsageHistoryResponse,
    CheckoutSessionResponse,
    CheckoutStatusResponse,
    CreditLedgerEntryResponse,
    PlanInfo,
)
from app.schemas.common import ApiEnvelope
from app.services.credit_catalog import (
    FY_DAYS,
    PLAN_ENTERPRISE,
    PLAN_FREE,
    PLAN_STUDIO,
    pricing_region_for_country,
    region_currency,
)
from app.services.credit_service import (
    get_tenant_plan_features,
    list_credit_ledger,
    refresh_tenant_billing,
    tenant_credits_consumed,
    top_up_credits,
    upgrade_to_studio,
)
from app.services.payments.stripe_platform_billing_service import (
    CheckoutSessionResult,
    SignupFreeResult,
    create_signup_checkout_session,
    create_subscription_upgrade_checkout,
    create_topup_checkout_session,
    get_checkout_status,
    get_signup_checkout_status,
    public_plans_for_country,
    resolve_ledger_invoice_links,
)

router = APIRouter(prefix="/billing", tags=["billing"])
public_router = APIRouter(prefix="/billing", tags=["billing-public"])


def _ledger_row(row) -> CreditLedgerEntryResponse:
    return CreditLedgerEntryResponse(
        id=row.id,
        event_type=row.event_type,
        description=row.description,
        pages=row.pages,
        credits_per_page=row.credits_per_page,
        credits_delta=row.credits_delta,
        balance_after=row.balance_after,
        plan_at_event=row.plan_at_event,
        amount_paid=float(row.amount_paid) if row.amount_paid is not None else None,
        currency_code=row.currency_code,
        azure_cost_usd=float(row.azure_cost_usd) if row.azure_cost_usd is not None else None,
        azure_cost_breakdown=row.azure_cost_breakdown_json,
        filename=row.filename,
        invoice_id=row.invoice_id,
        stripe_hosted_invoice_url=row.stripe_hosted_invoice_url,
        stripe_receipt_url=row.stripe_receipt_url,
        created_at=row.created_at,
    )


def _checkout_response(
    result: CheckoutSessionResult | SignupFreeResult,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    user: UserResponse | None = None,
) -> CheckoutSessionResponse:
    if isinstance(result, SignupFreeResult):
        return CheckoutSessionResponse(
            checkout_url=None,
            session_id=None,
            status="completed",
            tenant_id=str(result.tenant_id),
            completed_without_checkout=True,
            access_token=access_token,
            refresh_token=refresh_token,
            user=user,
        )
    return CheckoutSessionResponse(
        checkout_url=result.checkout_url,
        session_id=result.session_id,
        status=result.status,
        pending_signup_id=result.pending_signup_id,
        tenant_id=result.tenant_id,
        completed_without_checkout=False,
    )


async def _billing_state(session: AsyncSession, tenant_id) -> BillingStateResponse:
    settings = get_settings()
    billing = await refresh_tenant_billing(session, tenant_id)
    features = await get_tenant_plan_features(session, tenant_id)
    consumed = await tenant_credits_consumed(session, tenant_id)
    from datetime import date

    today = date.today()
    days_elapsed = (today - billing.billing_anchor_date).days
    fy_remaining = max(0, FY_DAYS - days_elapsed)

    plan_info = PlanInfo(
        plan=features["plan"],
        region=features["region"],
        currency_code=features["currency_code"],
        monthly_credits=features["monthly_credits"],
        max_users=features["max_users"],
        social_integration=features["social_integration"],
        email_integration=features["email_integration"],
        studio_monthly_price=features["studio_monthly_price"],
        credits_per_page=features["credits_per_page"],
        topup_factor=features["topup_factor"],
    )
    return BillingStateResponse(
        balance=features["credit_balance"],
        plan=features["plan"],
        credits_per_page=features["credits_per_page"],
        credits_consumed=consumed,
        plan_info=plan_info,
        billing_anchor_date=billing.billing_anchor_date.isoformat(),
        fy_days_remaining=fy_remaining,
        can_upgrade_studio=features["plan"] == PLAN_FREE,
        can_top_up=features["plan"] != PLAN_ENTERPRISE,
        is_enterprise=features["plan"] == PLAN_ENTERPRISE,
        platform_billing_enabled=settings.stripe_platform_billing_active,
        subscription_status=billing.subscription_status,
    )


@public_router.get("/plans", response_model=ApiEnvelope[BillingPlansResponse])
async def get_billing_plans(
    country: str = Query(..., min_length=2, max_length=2),
) -> ApiEnvelope[BillingPlansResponse]:
    settings = get_settings()
    region = pricing_region_for_country(country)
    plans = [
        BillingPlanCatalogItem.model_validate(plan)
        for plan in public_plans_for_country(country)
    ]
    return ApiEnvelope(
        data=BillingPlansResponse(
            country=country.upper(),
            region=region,
            currency_code=region_currency(region),
            plans=plans,
            platform_billing_enabled=settings.stripe_platform_billing_active,
        )
    )


@public_router.post("/signup/checkout", response_model=ApiEnvelope[CheckoutSessionResponse])
async def post_signup_checkout(
    body: BillingSignupCheckoutRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[CheckoutSessionResponse]:
    result = await create_signup_checkout_session(
        db,
        email=body.email,
        password=body.password,
        organisation_name=body.organisation_name,
        country=body.country,
        plan_code=body.plan_code,
        industry=body.industry,
        full_name=body.full_name,
        signup_token=body.signup_token,
        signup_source=body.signup_source,
    )
    await db.commit()

    if isinstance(result, SignupFreeResult):
        user = await db.get(User, result.user_id)
        tenant = await db.get(Tenant, result.tenant_id)
        if not user or not tenant:
            raise HTTPException(500, "Account was created but login could not be established")
        access, refresh = await _mint_session_tokens(
            db,
            user=user,
            tenant=tenant,
            role=user.role.value,
        )
        return ApiEnvelope(
            data=_checkout_response(
                result,
                access_token=access,
                refresh_token=refresh,
                user=_user_response(user, tenant),
            )
        )

    return ApiEnvelope(data=_checkout_response(result))


@public_router.get("/signup/status/{session_id}", response_model=ApiEnvelope[CheckoutStatusResponse])
async def get_signup_checkout_status_endpoint(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[CheckoutStatusResponse]:
    data = await get_signup_checkout_status(db, session_id=session_id)
    return ApiEnvelope(data=CheckoutStatusResponse.model_validate(data))


@router.get("", response_model=ApiEnvelope[BillingStateResponse])
async def get_billing(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingStateResponse]:
    return ApiEnvelope(data=await _billing_state(db, ctx.tenant_id))


@router.get("/usage", response_model=ApiEnvelope[BillingUsageHistoryResponse])
async def get_billing_usage(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = Query(
        None,
        pattern=r"^(usage|invoice)$",
        description="Filter ledger: 'usage' = credit consumption, 'invoice' = billing events",
    ),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingUsageHistoryResponse]:
    offset = (page - 1) * page_size
    rows, total = await list_credit_ledger(
        db, ctx.tenant_id, limit=page_size, offset=offset, category=category
    )
    # For the Invoices tab, backfill hosted invoice / receipt URLs from Stripe so
    # top-ups and subscription signups link out to the Stripe-hosted invoice page.
    if category == "invoice" and rows:
        try:
            if await resolve_ledger_invoice_links(db, rows):
                await db.commit()
        except Exception:  # pragma: no cover - never let link resolution break the page
            await db.rollback()
    pages = max(1, (total + page_size - 1) // page_size)
    return ApiEnvelope(
        data=BillingUsageHistoryResponse(
            items=[_ledger_row(r) for r in rows],
            total=total,
            page=page,
            pages=pages,
        )
    )


@router.post("/top-up", response_model=ApiEnvelope[BillingStateResponse])
async def post_billing_top_up(
    body: BillingTopUpRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingStateResponse]:
    """Simulated top-up when platform billing is disabled."""
    settings = get_settings()
    if settings.stripe_platform_billing_active:
        raise HTTPException(400, "Use POST /billing/topup/checkout for credit top-ups")
    features = await get_tenant_plan_features(db, ctx.tenant_id)
    if features["plan"] == PLAN_ENTERPRISE:
        raise HTTPException(400, "Enterprise top-up is managed by your account team")
    try:
        await top_up_credits(db, ctx.tenant_id, amount=body.amount)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=await _billing_state(db, ctx.tenant_id))


@router.post("/topup/checkout", response_model=ApiEnvelope[CheckoutSessionResponse])
async def post_topup_checkout(
    body: BillingTopUpCheckoutRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[CheckoutSessionResponse]:
    result = await create_topup_checkout_session(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        user_email=ctx.email,
        amount=body.amount,
    )
    await db.commit()
    return ApiEnvelope(data=_checkout_response(result))


@router.get("/checkout/status/{session_id}", response_model=ApiEnvelope[CheckoutStatusResponse])
async def get_checkout_status_endpoint(
    session_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[CheckoutStatusResponse]:
    data = await get_checkout_status(
        db,
        session_id=session_id,
        tenant_id=ctx.tenant_id,
    )
    if data.get("fulfilled"):
        await db.commit()
    return ApiEnvelope(data=CheckoutStatusResponse.model_validate(data))


@router.post("/upgrade", response_model=ApiEnvelope[BillingStateResponse | CheckoutSessionResponse])
async def post_billing_upgrade(
    body: BillingUpgradeRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingStateResponse | CheckoutSessionResponse]:
    if body.plan != PLAN_STUDIO:
        raise HTTPException(400, "Only Studio self-serve upgrade is supported")

    settings = get_settings()
    if settings.stripe_platform_billing_active:
        result = await create_subscription_upgrade_checkout(
            db,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            user_email=ctx.email,
        )
        await db.commit()
        return ApiEnvelope(data=_checkout_response(result))

    try:
        await upgrade_to_studio(db, ctx.tenant_id)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=await _billing_state(db, ctx.tenant_id))
