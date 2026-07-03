"""Tenant billing credits API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.billing import (
    BillingStateResponse,
    BillingTopUpRequest,
    BillingUpgradeRequest,
    BillingUsageHistoryResponse,
    CreditLedgerEntryResponse,
    PlanInfo,
)
from app.schemas.common import ApiEnvelope
from app.services.credit_catalog import FY_DAYS, PLAN_ENTERPRISE, PLAN_FREE, PLAN_STUDIO
from app.services.credit_service import (
    InsufficientCreditsError,
    get_tenant_plan_features,
    list_credit_ledger,
    refresh_tenant_billing,
    tenant_credits_consumed,
    top_up_credits,
    upgrade_to_studio,
)

router = APIRouter(prefix="/billing", tags=["billing"])


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
        created_at=row.created_at,
    )


async def _billing_state(session: AsyncSession, tenant_id) -> BillingStateResponse:
    billing = await refresh_tenant_billing(session, tenant_id)
    features = await get_tenant_plan_features(session, tenant_id)
    consumed = await tenant_credits_consumed(session, tenant_id)
    from datetime import date

    today = date.today()
    fy_end = billing.billing_anchor_date.replace(year=billing.billing_anchor_date.year)
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
    )


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
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingUsageHistoryResponse]:
    offset = (page - 1) * page_size
    rows, total = await list_credit_ledger(db, ctx.tenant_id, limit=page_size, offset=offset)
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
    """Dummy payment success — Stripe integration deferred."""
    features = await get_tenant_plan_features(db, ctx.tenant_id)
    if features["plan"] == PLAN_ENTERPRISE:
        raise HTTPException(400, "Enterprise top-up is managed by your account team")
    try:
        await top_up_credits(db, ctx.tenant_id, amount=body.amount)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=await _billing_state(db, ctx.tenant_id))


@router.post("/upgrade", response_model=ApiEnvelope[BillingStateResponse])
async def post_billing_upgrade(
    body: BillingUpgradeRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ApiEnvelope[BillingStateResponse]:
    """Dummy Stripe success — upgrades Free to Studio immediately."""
    if body.plan != PLAN_STUDIO:
        raise HTTPException(400, "Only Studio self-serve upgrade is supported")
    try:
        await upgrade_to_studio(db, ctx.tenant_id)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=await _billing_state(db, ctx.tenant_id))
