"""Payment disbursement workflow API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.payment import PaymentResponse, PaymentStatusUpdate, WalletSummaryResponse
from app.services.audit_service import log_event
from app.services.payment_service import list_payments, update_payment_status, wallet_summary

router = APIRouter(prefix="/payments", tags=["payments"])


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
