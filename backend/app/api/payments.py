"""Payment disbursement workflow API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.config import get_settings
from app.schemas.common import ApiEnvelope
from app.schemas.payment import (
    PaymentResponse,
    PaymentStatusUpdate,
    StripeAccountResponse,
    StripeBalanceAmountResponse,
    StripeBalanceResponse,
    StripeConnectResponse,
    StripeOnboardingLinkResponse,
    StripeTransactionResponse,
    WalletSummaryResponse,
)
from app.services.audit_service import log_event
from app.services.payment_service import list_payments, update_payment_status, wallet_summary
from app.services.stripe_service import (
    StripeServiceError,
    create_account_onboarding_link,
    create_connected_account_for_tenant,
    get_connected_account_balance,
    get_stripe_account_for_tenant,
    list_connected_account_transactions,
)

router = APIRouter(prefix="/payments", tags=["payments"])


def _stripe_http_error(exc: StripeServiceError) -> HTTPException:
    message = str(exc)
    lowered = message.lower()
    if "not configured" in lowered:
        return HTTPException(503, message)
    if "not found" in lowered:
        return HTTPException(404, message)
    return HTTPException(400, message)


def _account_needs_onboarding(account: object) -> bool:
    status = getattr(account, "onboarding_status", None)
    if status == "complete":
        return False
    if not getattr(account, "details_submitted", False):
        return True
    if not getattr(account, "charges_enabled", False):
        return True
    if not getattr(account, "payouts_enabled", False):
        return True
    return status in (None, "pending", "action_required")


async def _optional_onboarding_url(
    stripe_account_id: str,
    *,
    needs_onboarding: bool,
) -> str | None:
    if not needs_onboarding:
        return None
    settings = get_settings()
    if not settings.stripe_return_url.strip() or not settings.stripe_refresh_url.strip():
        return None
    try:
        return await create_account_onboarding_link(stripe_account_id)
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc


async def _require_connected_account(db: AsyncSession, tenant_id) -> object:
    account = await get_stripe_account_for_tenant(db, tenant_id)
    if account is None:
        raise HTTPException(404, "Stripe connected account not found")
    return account


@router.get("/stripe/account", response_model=ApiEnvelope[StripeAccountResponse])
async def get_stripe_account(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeAccountResponse]:
    account = await get_stripe_account_for_tenant(db, ctx.tenant_id)
    if account is None:
        raise HTTPException(404, "Stripe connected account not found")
    return ApiEnvelope(data=StripeAccountResponse.model_validate(account))


@router.post("/stripe/connect", response_model=ApiEnvelope[StripeConnectResponse])
async def post_stripe_connect(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeConnectResponse]:
    tenant_name = ctx.tenant.name if ctx.tenant is not None else None
    try:
        account = await create_connected_account_for_tenant(
            db,
            ctx.tenant_id,
            tenant_name=tenant_name,
        )
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc

    account_response = StripeAccountResponse.model_validate(account)
    onboarding_url = await _optional_onboarding_url(
        account.stripe_account_id,
        needs_onboarding=_account_needs_onboarding(account),
    )
    return ApiEnvelope(
        data=StripeConnectResponse(
            account=account_response,
            onboarding_url=onboarding_url,
        )
    )


@router.get("/stripe/onboarding-link", response_model=ApiEnvelope[StripeOnboardingLinkResponse])
async def get_stripe_onboarding_link(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeOnboardingLinkResponse]:
    account = await _require_connected_account(db, ctx.tenant_id)
    try:
        url = await create_account_onboarding_link(account.stripe_account_id)
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc
    return ApiEnvelope(data=StripeOnboardingLinkResponse(url=url))


@router.get("/stripe/balance", response_model=ApiEnvelope[StripeBalanceResponse])
async def get_stripe_balance(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeBalanceResponse]:
    account = await _require_connected_account(db, ctx.tenant_id)
    try:
        summary = await get_connected_account_balance(
            db,
            ctx.tenant_id,
            account.stripe_account_id,
        )
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc
    return ApiEnvelope(
        data=StripeBalanceResponse(
            available=[
                StripeBalanceAmountResponse.model_validate(item) for item in summary.available
            ],
            pending=[
                StripeBalanceAmountResponse.model_validate(item) for item in summary.pending
            ],
            livemode=summary.livemode,
            snapshot_id=summary.snapshot_id,
        )
    )


@router.get("/stripe/transactions", response_model=ApiEnvelope[list[StripeTransactionResponse]])
async def get_stripe_transactions(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[StripeTransactionResponse]]:
    account = await _require_connected_account(db, ctx.tenant_id)
    try:
        rows = await list_connected_account_transactions(
            db,
            ctx.tenant_id,
            account.stripe_account_id,
            limit=limit,
        )
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc
    return ApiEnvelope(
        data=[StripeTransactionResponse.model_validate(row) for row in rows]
    )


@router.get("/wallet-summary", response_model=ApiEnvelope[WalletSummaryResponse])
async def get_wallet_summary(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[WalletSummaryResponse]:
    data = await wallet_summary(db, ctx.tenant_id)
    return ApiEnvelope(data=data)


@router.get("", response_model=ApiEnvelope[list[PaymentResponse]])
async def get_payments(
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[PaymentResponse]]:
    rows = await list_payments(db, ctx.tenant_id, status=status)
    return ApiEnvelope(data=rows)


@router.patch("/{payment_id}", response_model=ApiEnvelope[PaymentResponse])
async def patch_payment(
    payment_id: int,
    body: PaymentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PaymentResponse]:
    try:
        from sqlalchemy import select

        from app.models.payment import Payment

        existing = (
            await db.execute(
                select(Payment).where(
                    Payment.id == payment_id,
                    Payment.tenant_id == ctx.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise LookupError("Payment not found")
        previous_status = existing.status.value
        row = await update_payment_status(db, ctx.tenant_id, payment_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "payment_status_updated",
        invoice_id=row.invoice_id,
        tenant_id=ctx.tenant_id,
        detail={
            "payment_id": payment_id,
            "previous_status": previous_status,
            "new_status": row.status,
            "vendor": row.vendor,
            "amount": float(row.amount) if row.amount is not None else None,
            "scheduled_date": row.scheduled_date.isoformat() if row.scheduled_date else None,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(data=row)
