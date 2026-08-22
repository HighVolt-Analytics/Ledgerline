"""Payment disbursement workflow API."""

from urllib.parse import urlencode
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, bind_db_to_tenant, get_auth_context, get_db
from app.config import get_settings
from app.schemas.common import ApiEnvelope
from app.schemas.payment import (
    PaymentExecutionInstructionExportResponse,
    PaymentExecutionInstructionResponse,
    PaymentExecutionReadinessResponse,
    PaymentMarkPaidManualRequest,
    PaymentResponse,
    PaymentStatusUpdate,
    PaymentWorkspaceKpis,
    StripeAccountResponse,
    StripeBalanceAmountResponse,
    StripeBalanceResponse,
    StripeConnectResponse,
    StripeDisconnectResponse,
    StripeOAuthUrlResponse,
    StripeOnboardingLinkResponse,
    StripeGlobalPayoutsReadinessResponse,
    StripeReadinessResponse,
    StripeTransactionResponse,
    WalletSummaryResponse,
)
from app.services.audit.audit_service import log_event
from app.services.payments.payment_service import (
    approve_payment,
    list_payments,
    payment_workspace_kpis,
    update_payment_status,
    wallet_summary,
)
from app.services.payments.payment_execution_readiness_service import validate_payment_execution_readiness
from app.services.payments.payment_execution_instruction_service import (
    PaymentExecutionBlockedError,
    create_payment_execution_instruction,
    export_payment_execution_instruction,
    mark_payment_paid_manual,
)
from app.services.payments.payment_execution_auth import (
    PaymentExecutionUnauthorizedError,
    require_payment_execution_role,
)
from app.services.payments.stripe_global_payouts_service import stripe_global_payouts_readiness_payload
from app.services.payments.stripe_service import (
    StripeServiceError,
    create_account_onboarding_link,
    create_connected_account_for_tenant,
    create_stripe_oauth_state,
    create_stripe_oauth_url,
    disconnect_stripe_account_for_tenant,
    exchange_stripe_oauth_code,
    get_connected_account_balance,
    get_stripe_account_for_tenant,
    get_stripe_readiness_for_tenant,
    list_connected_account_transactions,
    parse_stripe_oauth_state,
    refresh_connected_account_status,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

# Stripe OAuth browser callback — no JWT (mounted without require_user in main.py).
oauth_public_router = APIRouter(prefix="/payments", tags=["payments"])


def _append_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _stripe_oauth_return_url() -> str:
    settings = get_settings()
    return_url = settings.stripe_return_url.strip()
    if return_url:
        return return_url.rstrip("/")
    base = settings.public_app_url.strip().rstrip("/")
    if base:
        return f"{base}/payments"
    return "/payments"


def _stripe_oauth_redirect(*, outcome: str, message: str | None = None) -> RedirectResponse:
    params = {"stripe": outcome}
    if message:
        params["message"] = message[:200]
    return RedirectResponse(_append_query(_stripe_oauth_return_url(), params))


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
    if status == "disconnected":
        return False
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


@router.get("/stripe/readiness", response_model=ApiEnvelope[StripeReadinessResponse])
async def get_stripe_readiness(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeReadinessResponse]:
    readiness = await get_stripe_readiness_for_tenant(db, ctx.tenant_id)
    return ApiEnvelope(data=StripeReadinessResponse.model_validate(readiness))


@router.get(
    "/stripe/global-payouts/readiness",
    response_model=ApiEnvelope[StripeGlobalPayoutsReadinessResponse],
)
async def get_stripe_global_payouts_readiness_endpoint(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeGlobalPayoutsReadinessResponse]:
    _ = ctx
    readiness_payload = stripe_global_payouts_readiness_payload()
    return ApiEnvelope(
        data=StripeGlobalPayoutsReadinessResponse.model_validate(readiness_payload),
    )


@router.post("/stripe/account/refresh", response_model=ApiEnvelope[StripeAccountResponse])
async def post_stripe_account_refresh(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeAccountResponse]:
    account = await get_stripe_account_for_tenant(db, ctx.tenant_id)
    if account is None:
        raise HTTPException(404, "Stripe connected account not found")
    try:
        account = await refresh_connected_account_status(db, account)
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "stripe_status_refreshed",
        tenant_id=ctx.tenant_id,
        detail={
            "stripe_account_id": account.stripe_account_id,
            "onboarding_status": account.onboarding_status,
            "charges_enabled": account.charges_enabled,
            "payouts_enabled": account.payouts_enabled,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(data=StripeAccountResponse.model_validate(account))


@router.delete("/stripe/account", response_model=ApiEnvelope[StripeDisconnectResponse])
async def delete_stripe_account(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeDisconnectResponse]:
    try:
        await disconnect_stripe_account_for_tenant(db, ctx.tenant_id)
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc

    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "stripe_account_disconnected",
        tenant_id=ctx.tenant_id,
        detail={"tenant_id": str(ctx.tenant_id)},
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(data=StripeDisconnectResponse(disconnected=True))


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
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "stripe_account_connected_onboarding",
        tenant_id=ctx.tenant_id,
        detail={
            "stripe_account_id": account.stripe_account_id,
            "account_type": account.account_type,
            "onboarding_status": account.onboarding_status,
        },
        actor_name=actor_name,
        actor_email=actor_email,
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


@router.get("/stripe/oauth-url", response_model=ApiEnvelope[StripeOAuthUrlResponse])
async def get_stripe_oauth_url(
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[StripeOAuthUrlResponse]:
    try:
        state = create_stripe_oauth_state(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        url = create_stripe_oauth_url(ctx.tenant_id, state)
    except StripeServiceError as exc:
        raise _stripe_http_error(exc) from exc
    return ApiEnvelope(data=StripeOAuthUrlResponse(url=url))


@oauth_public_router.get("/stripe/oauth/callback")
async def stripe_oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Stripe Connect OAuth redirect target — exchanges code and returns user to Payments."""
    if error:
        return _stripe_oauth_redirect(
            outcome="oauth_error",
            message=(error_description or error),
        )

    if not code or not state:
        return _stripe_oauth_redirect(
            outcome="oauth_error",
            message="Missing authorization code",
        )

    try:
        payload = parse_stripe_oauth_state(state)
        tenant_id = payload["tenant_id"]
        if not isinstance(tenant_id, uuid.UUID):
            tenant_id = uuid.UUID(str(tenant_id))
        await bind_db_to_tenant(db, tenant_id)
        await exchange_stripe_oauth_code(db, tenant_id, code)
        account = await get_stripe_account_for_tenant(db, tenant_id)
        await log_event(
            db,
            "stripe_account_connected_oauth",
            tenant_id=tenant_id,
            detail={
                "stripe_account_id": account.stripe_account_id if account else None,
            },
        )
        await db.commit()
    except (ValueError, StripeServiceError) as exc:
        await db.rollback()
        logger.warning("stripe_oauth_callback_failed", error=str(exc))
        return _stripe_oauth_redirect(outcome="oauth_error", message=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.exception("stripe_oauth_callback_failed", error=str(exc))
        return _stripe_oauth_redirect(
            outcome="oauth_error",
            message="Stripe connection failed. Try again or contact support.",
        )

    return _stripe_oauth_redirect(outcome="connected")


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


_LIST_LIMIT_MAX = 200


@router.get("/wallet-summary", response_model=ApiEnvelope[WalletSummaryResponse])
async def get_wallet_summary(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[WalletSummaryResponse]:
    data = await wallet_summary(db, ctx.tenant_id)
    return ApiEnvelope(data=data)


@router.get("/kpis", response_model=ApiEnvelope[PaymentWorkspaceKpis])
async def get_payment_workspace_kpis(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PaymentWorkspaceKpis]:
    data = await payment_workspace_kpis(db, ctx.tenant_id, tenant=ctx.tenant)
    return ApiEnvelope(data=data)


@router.get("", response_model=ApiEnvelope[list[PaymentResponse]])
async def get_payments(
    status: str | None = Query(None),
    limit: int | None = Query(default=None, ge=1, le=_LIST_LIMIT_MAX),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[PaymentResponse]]:
    try:
        rows = await list_payments(db, ctx.tenant_id, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
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


@router.post("/{payment_id}/approve", response_model=ApiEnvelope[PaymentResponse])
async def post_payment_approve(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PaymentResponse]:
    """Approve a payment awaiting release (single approver = logged-in user)."""
    try:
        require_payment_execution_role(ctx)
    except PaymentExecutionUnauthorizedError as exc:
        raise HTTPException(403, str(exc)) from exc

    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row, changed = await approve_payment(
            db,
            ctx.tenant_id,
            payment_id,
            actor={
                "user_id": ctx.user_id,
                "name": actor_name,
                "email": actor_email,
            },
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if changed:
        await log_event(
            db,
            "payment_approved",
            invoice_id=row.invoice_id,
            tenant_id=ctx.tenant_id,
            detail={
                "payment_id": payment_id,
                "vendor": row.vendor,
                "amount": row.amount,
                "approver_id": ctx.user_id,
                "approver_name": actor_name,
                "approver_email": actor_email,
                "scheduled_date": row.scheduled_date.isoformat() if row.scheduled_date else None,
            },
            actor_name=actor_name,
            actor_email=actor_email,
        )
    return ApiEnvelope(data=row)


@router.post(
    "/{payment_id}/execution-readiness",
    response_model=ApiEnvelope[PaymentExecutionReadinessResponse],
)
async def post_payment_execution_readiness(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PaymentExecutionReadinessResponse]:
    try:
        result = await validate_payment_execution_readiness(
            db,
            ctx.tenant_id,
            payment_id,
            actor={
                "user_id": ctx.user_id,
                "role": ctx.role,
            },
            ctx=ctx,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    actor_name, actor_email = await actor_from_context(db, ctx)
    from sqlalchemy import select

    from app.models.payment import Payment

    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    await log_event(
        db,
        "payment_execution_readiness_validated",
        invoice_id=payment.invoice_id if payment else None,
        tenant_id=ctx.tenant_id,
        detail={
            "payment_id": payment_id,
            "can_execute": result.can_execute,
            "execution_mode": result.execution_mode,
            "blocking_reasons": result.blocking_reasons,
            "warnings": result.warnings,
            "tenant_stripe_ready": result.tenant_stripe_ready,
            "vendor_payout_ready": result.vendor_payout_ready,
            "approval_ready": result.approval_ready,
            "amount_ready": result.amount_ready,
            "manual_execution_ready": result.manual_execution_ready,
            "role_ready": result.role_ready,
            "limit_ready": result.limit_ready,
            "tenant_execution_enabled": result.tenant_execution_enabled,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(
        data=PaymentExecutionReadinessResponse.model_validate(result),
    )


async def _log_execution_block(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    payment_id: int,
    action: str,
    reason: str,
    reason_code: str,
    actor_name: str,
    actor_email: str,
) -> None:
    from sqlalchemy import select

    from app.models.payment import Payment

    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    event = "payment_execution_blocked_by_safety_gate"
    if reason_code == "tenant_disabled":
        event = "payment_execution_blocked_by_tenant_disable"
    elif reason_code == "limit_exceeded":
        event = "payment_execution_blocked_by_limit"
    await log_event(
        db,
        event,
        invoice_id=payment.invoice_id if payment else None,
        tenant_id=tenant_id,
        detail={
            "payment_id": payment_id,
            "action": action,
            "reason": reason,
            "reason_code": reason_code,
            "vendor": payment.vendor if payment else None,
            "amount": float(payment.amount) if payment and payment.amount is not None else None,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )


def _actor_payload(ctx: AuthContext, actor_name: str, actor_email: str) -> dict:
    return {
        "user_id": ctx.user_id,
        "name": actor_name,
        "email": actor_email,
        "role": ctx.role,
    }


@router.post(
    "/{payment_id}/execution-instruction",
    response_model=ApiEnvelope[PaymentExecutionInstructionResponse],
)
async def post_payment_execution_instruction(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PaymentExecutionInstructionResponse]:
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        instruction, created = await create_payment_execution_instruction(
            db,
            ctx.tenant_id,
            payment_id,
            actor=_actor_payload(ctx, actor_name, actor_email),
            ctx=ctx,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PaymentExecutionUnauthorizedError as exc:
        raise HTTPException(403, str(exc)) from exc
    except PaymentExecutionBlockedError as exc:
        await _log_execution_block(
            db,
            tenant_id=ctx.tenant_id,
            payment_id=payment_id,
            action="create_instruction",
            reason=str(exc),
            reason_code=exc.reason_code,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if created:
        from sqlalchemy import select

        from app.models.payment import Payment

        payment = (
            await db.execute(
                select(Payment).where(
                    Payment.id == payment_id,
                    Payment.tenant_id == ctx.tenant_id,
                )
            )
        ).scalar_one_or_none()
        await log_event(
            db,
            "payment_execution_instruction_created",
            invoice_id=payment.invoice_id if payment else None,
            tenant_id=ctx.tenant_id,
            detail={
                "payment_id": payment_id,
                "instruction_id": instruction.id,
                "instruction_reference": instruction.instruction_reference,
                "vendor": instruction.vendor_name,
                "amount": instruction.amount,
                "currency": instruction.currency,
                "execution_mode": instruction.execution_mode,
            },
            actor_name=actor_name,
            actor_email=actor_email,
        )
    return ApiEnvelope(data=instruction)


@router.get(
    "/{payment_id}/execution-instruction/export",
    response_model=ApiEnvelope[PaymentExecutionInstructionExportResponse],
)
async def get_payment_execution_instruction_export(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PaymentExecutionInstructionExportResponse]:
    try:
        export_row = await export_payment_execution_instruction(
            db,
            ctx.tenant_id,
            payment_id,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ApiEnvelope(data=export_row)


@router.post("/{payment_id}/mark-paid-manual", response_model=ApiEnvelope[PaymentResponse])
async def post_payment_mark_paid_manual(
    payment_id: int,
    body: PaymentMarkPaidManualRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PaymentResponse]:
    actor_name, actor_email = await actor_from_context(db, ctx)
    try:
        row, changed = await mark_payment_paid_manual(
            db,
            ctx.tenant_id,
            payment_id,
            body,
            actor=_actor_payload(ctx, actor_name, actor_email),
            ctx=ctx,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PaymentExecutionUnauthorizedError as exc:
        raise HTTPException(403, str(exc)) from exc
    except PaymentExecutionBlockedError as exc:
        await _log_execution_block(
            db,
            tenant_id=ctx.tenant_id,
            payment_id=payment_id,
            action="mark_paid_manual",
            reason=str(exc),
            reason_code=exc.reason_code,
            actor_name=actor_name,
            actor_email=actor_email,
        )
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if changed:
        await log_event(
            db,
            "payment_marked_paid_manual",
            invoice_id=row.invoice_id,
            tenant_id=ctx.tenant_id,
            detail={
                "payment_id": payment_id,
                "vendor": row.vendor,
                "amount": row.amount,
                "reference": body.reference,
                "proof_reference": body.proof_reference,
                "paid_date": body.paid_date.isoformat(),
                "note": body.note,
            },
            actor_name=actor_name,
            actor_email=actor_email,
        )
    return ApiEnvelope(data=row)
