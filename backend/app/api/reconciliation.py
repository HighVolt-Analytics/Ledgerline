from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request
from app.schemas.common import ApiEnvelope
from app.schemas.reconciliation import ReconciliationOverview, ReconciliationResponse
from app.services.reconciliation_api_service import (
    get_daily_reconciliation,
    list_daily_reconciliations,
)
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
    return ApiEnvelope(
        data=await list_daily_reconciliations(db, tenant_id=ctx.tenant_id)
    )


@router.get("/daily/{recon_date}", response_model=ApiEnvelope[ReconciliationResponse])
async def get_daily(
    recon_date: date,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReconciliationResponse]:
    row = await get_daily_reconciliation(
        db, tenant_id=ctx.tenant_id, recon_date=recon_date
    )
    if not row:
        raise HTTPException(404, "Reconciliation not found")
    return ApiEnvelope(data=row)
