from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.reconciliation import (
    ReconciliationDayDetail,
    ReconciliationOverview,
    ReconciliationResponse,
    StrandedJournalPurgeResponse,
)
from app.services.reconciliation.reconciliation_api_service import (
    build_reconciliation_day_detail,
    get_daily_reconciliation,
    list_daily_reconciliations,
)
from app.services.reconciliation.reconciliation_overview import build_reconciliation_overview
from app.services.reconciliation.stranded_journal_remediation import (
    purge_stranded_accrual_journals,
)

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


@router.get("/daily/{recon_date}/detail", response_model=ApiEnvelope[ReconciliationDayDetail])
async def get_daily_detail(
    recon_date: date,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReconciliationDayDetail]:
    """RC1/RC2 drill-down with journal lines for a single day."""
    return ApiEnvelope(
        data=await build_reconciliation_day_detail(
            db, tenant_id=ctx.tenant_id, recon_date=recon_date
        )
    )


@router.post(
    "/purge-stranded-accruals",
    response_model=ApiEnvelope[StrandedJournalPurgeResponse],
)
async def purge_stranded_accruals(
    recon_date: Annotated[date | None, Query()] = None,
    invoice_id: Annotated[int | None, Query(ge=1)] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[StrandedJournalPurgeResponse]:
    """Delete accrual journals for incomplete (EXCEPTION/REJECTED/DUPLICATE) invoices.

    Use after RC1 logic change to clean already-stranded rows (e.g. awaiting_po
    holds that wrote journals then halted). Optional ``recon_date`` / ``invoice_id``.
    """
    result = await purge_stranded_accrual_journals(
        db,
        tenant_id=ctx.tenant_id,
        recon_date=recon_date,
        invoice_id=invoice_id,
        reason="admin_remediation",
    )
    await db.commit()
    return ApiEnvelope(
        data=StrandedJournalPurgeResponse(
            invoice_ids=result.invoice_ids,
            entries_deleted=result.entries_deleted,
            recon_date=recon_date,
        )
    )
