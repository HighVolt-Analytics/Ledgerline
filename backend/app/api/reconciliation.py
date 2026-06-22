from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.models.reconciliation import DailyReconciliation
from app.schemas.common import ApiEnvelope
from app.schemas.reconciliation import ReconciliationOverview, ReconciliationResponse
from app.services.reconciliation_overview import build_reconciliation_overview

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("/overview", response_model=ApiEnvelope[ReconciliationOverview])
async def reconciliation_overview(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReconciliationOverview]:
    """Processed invoices with journal postings, grouped by invoice date."""
    return ApiEnvelope(
        data=await build_reconciliation_overview(db, tenant_id=ctx.tenant_id)
    )


@router.get("/daily", response_model=ApiEnvelope[list[ReconciliationResponse]])
async def list_daily(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ReconciliationResponse]]:
    """Daily closed-loop batch summaries (legacy ledger table)."""
    rows = (
        await db.execute(
            select(DailyReconciliation)
            .where(DailyReconciliation.tenant_id == ctx.tenant_id)
            .order_by(DailyReconciliation.date.desc())
        )
    ).scalars().all()
    return ApiEnvelope(
        data=[ReconciliationResponse.model_validate(r) for r in rows]
    )


@router.get("/daily/{recon_date}", response_model=ApiEnvelope[ReconciliationResponse])
async def get_daily(
    recon_date: date,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReconciliationResponse]:
    row = (
        await db.execute(
            select(DailyReconciliation).where(
                DailyReconciliation.date == recon_date,
                DailyReconciliation.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Reconciliation not found")
    return ApiEnvelope(data=ReconciliationResponse.model_validate(row))
