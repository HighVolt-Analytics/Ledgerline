"""PayPal connected-payment API (tenant-owned execution — not platform billing)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.config import get_settings
from app.schemas.common import ApiEnvelope
from app.services.audit.audit_service import log_event
from app.services.payments.payment_execution_auth import (
    PaymentExecutionUnauthorizedError,
    require_payment_execution_role,
)
from app.services.payments.paypal_account_service import (
    PaypalAccountError,
    connect_paypal_account,
    disconnect_paypal_account,
    get_paypal_readiness,
    handle_paypal_oauth_callback,
)
from app.services.payments.paypal_balance_service import get_paypal_balance
from app.services.payments.paypal_payout_service import (
    PaypalPayoutError,
    create_paypal_payout,
    refresh_payout_attempt,
)
from app.services.payments.paypal_transaction_service import list_paypal_transactions
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/payments/paypal", tags=["paypal-payments"])
oauth_public_router = APIRouter(prefix="/payments/paypal", tags=["paypal-payments"])


class PaypalPayoutRequest(BaseModel):
    payable_id: int = Field(..., description="Payment id (approved payable)")
    recipient_method_id: int
    amount: str | None = None
    currency: str | None = None
    note: str | None = None


def _paypal_return_url() -> str:
    settings = get_settings()
    return_url = settings.paypal_return_url.strip()
    if return_url:
        return return_url.rstrip("/")
    base = settings.public_app_url.strip().rstrip("/") if hasattr(settings, "public_app_url") else ""
    if not base:
        base = settings.public_app_base_url.strip().rstrip("/")
    if base:
        return f"{base}/payments"
    return "/payments"


def _append_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _account_http_error(exc: PaypalAccountError) -> HTTPException:
    code = (exc.code or "").lower()
    message = str(exc)
    if code in {"paypal_not_configured", "capability_required"}:
        return HTTPException(503, detail={"message": message, "code": exc.code})
    if "not found" in message.lower():
        return HTTPException(404, message)
    return HTTPException(400, detail={"message": message, "code": exc.code})


def _payout_http_error(exc: PaypalPayoutError) -> HTTPException:
    code = (exc.code or "").lower()
    message = str(exc)
    if code in {"paypal_not_configured", "capability_required"}:
        return HTTPException(503, detail={"message": message, "code": exc.code})
    if code in {"payment_not_found", "recipient_not_found", "attempt_not_found"}:
        return HTTPException(404, detail={"message": message, "code": exc.code})
    if code in {"duplicate_payment", "payment_already_paid"}:
        return HTTPException(409, detail={"message": message, "code": exc.code})
    return HTTPException(400, detail={"message": message, "code": exc.code})


def _serialize_attempt(attempt) -> dict:
    return {
        "id": attempt.id,
        "payment_id": attempt.payment_id,
        "provider": attempt.provider,
        "provider_batch_id": attempt.provider_batch_id,
        "provider_item_id": attempt.provider_item_id,
        "provider_transaction_id": attempt.provider_transaction_id,
        "provider_request_id": attempt.provider_request_id,
        "provider_status": attempt.provider_status,
        "recipient_type": attempt.recipient_type,
        "recipient_value": attempt.recipient_value,
        "amount": str(attempt.amount) if attempt.amount is not None else None,
        "currency": attempt.currency,
        "status": attempt.status,
        "failure_code": attempt.failure_code,
        "failure_message": attempt.failure_message,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "last_checked_at": attempt.last_checked_at.isoformat() if attempt.last_checked_at else None,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
    }


@router.post("/connect")
async def paypal_connect(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    try:
        result = await connect_paypal_account(
            db,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
        )
    except PaypalAccountError as exc:
        raise _account_http_error(exc) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "paypal_connect_started",
        detail={"mode": result.get("mode"), "merchant_id": result.get("merchant_id")},
        actor_name=actor_name,
        actor_email=actor_email,
        tenant_id=ctx.tenant_id,
    )
    await db.commit()
    return ApiEnvelope(data=result)


@oauth_public_router.get("/callback")
async def paypal_oauth_callback(
    state: str = Query(...),
    merchantId: str | None = Query(None),
    merchantIdInPayPal: str | None = Query(None),
    trackingId: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    try:
        result = await handle_paypal_oauth_callback(
            db,
            state=state,
            merchant_id=merchantId or merchantIdInPayPal,
            tracking_id=trackingId,
        )
        await db.commit()
        outcome = "connected" if result.get("connected") else "pending"
        return RedirectResponse(
            _append_query(_paypal_return_url(), {"paypal": outcome})
        )
    except PaypalAccountError as exc:
        logger.info("paypal_oauth_callback_failed", error=str(exc), code=exc.code)
        return RedirectResponse(
            _append_query(
                _paypal_return_url(),
                {"paypal": "error", "message": str(exc)[:200]},
            )
        )


@router.get("/readiness")
async def paypal_readiness(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict]:
    data = await get_paypal_readiness(db, ctx.tenant_id)
    return ApiEnvelope(data=data)


@router.post("/disconnect")
async def paypal_disconnect(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[dict]:
    try:
        result = await disconnect_paypal_account(db, tenant_id=ctx.tenant_id)
    except PaypalAccountError as exc:
        raise _account_http_error(exc) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "paypal_account_disconnected",
        detail={},
        actor_name=actor_name,
        actor_email=actor_email,
        tenant_id=ctx.tenant_id,
    )
    await db.commit()
    return ApiEnvelope(data=result)


@router.get("/balance")
async def paypal_balance(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict]:
    data = await get_paypal_balance(db, tenant_id=ctx.tenant_id)
    return ApiEnvelope(data=data)


@router.get("/transactions")
async def paypal_transactions(
    limit: int = Query(50, ge=1, le=200),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict]:
    data = await list_paypal_transactions(
        db,
        tenant_id=ctx.tenant_id,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
    )
    return ApiEnvelope(data=data)


@router.post("/payouts")
async def paypal_create_payout(
    body: PaypalPayoutRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict]:
    try:
        require_payment_execution_role(ctx)
    except PaymentExecutionUnauthorizedError as exc:
        raise HTTPException(403, str(exc)) from exc

    amount: Decimal | None = None
    if body.amount is not None:
        try:
            amount = Decimal(str(body.amount))
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(400, "Invalid amount") from exc

    try:
        attempt = await create_paypal_payout(
            db,
            tenant_id=ctx.tenant_id,
            payment_id=body.payable_id,
            recipient_method_id=body.recipient_method_id,
            amount=amount,
            currency=body.currency,
            note=body.note,
            actor_user_id=ctx.user_id,
        )
    except PaypalPayoutError as exc:
        raise _payout_http_error(exc) from exc

    await log_event(
        db,
        "paypal_payout_submitted",
        detail={
            "payment_id": body.payable_id,
            "attempt_id": attempt.id,
            "status": attempt.status,
            "provider_batch_id": attempt.provider_batch_id,
        },
        actor_name=None,
        actor_email=None,
        tenant_id=ctx.tenant_id,
    )
    await db.commit()
    return ApiEnvelope(data=_serialize_attempt(attempt))


@router.post("/payouts/{attempt_id}/refresh")
async def paypal_refresh_payout(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict]:
    try:
        require_payment_execution_role(ctx)
    except PaymentExecutionUnauthorizedError as exc:
        raise HTTPException(403, str(exc)) from exc
    try:
        attempt = await refresh_payout_attempt(
            db,
            tenant_id=ctx.tenant_id,
            attempt_id=attempt_id,
        )
    except PaypalPayoutError as exc:
        raise _payout_http_error(exc) from exc
    await log_event(
        db,
        "paypal_payout_refreshed",
        detail={"attempt_id": attempt.id, "status": attempt.status},
        tenant_id=ctx.tenant_id,
    )
    await db.commit()
    return ApiEnvelope(data=_serialize_attempt(attempt))
