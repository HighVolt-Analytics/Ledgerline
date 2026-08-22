"""Ledger Link — journal overview and export register."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.ledger_link import LedgerLinkExports, LedgerLinkResponse
from app.schemas.reconciliation import ReconDayOverviewRow
from app.services.integration.ledger_link_service import (
    build_ledger_link,
    build_ledger_link_exports,
)
from app.services.reconciliation.reconciliation_overview import build_reconciliation_day_overview

router = APIRouter(prefix="/ledger-link", tags=["ledger-link"])

_EXPORT_GROUP_LIMIT = 50
_ALLOWED_FIELDS = frozenset({"overview", "exports"})


@router.get("/exports", response_model=ApiEnvelope[LedgerLinkExports])
async def get_ledger_link_exports(
    limit: int | None = Query(default=_EXPORT_GROUP_LIMIT, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[LedgerLinkExports]:
    data = await build_ledger_link_exports(db, tenant_id=ctx.tenant_id, limit=limit)
    return ApiEnvelope(data=data)


@router.get("/days/{day}", response_model=ApiEnvelope[ReconDayOverviewRow])
async def get_ledger_link_day(
    day: date,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ReconDayOverviewRow]:
    data = await build_reconciliation_day_overview(
        db, tenant_id=ctx.tenant_id, day=day
    )
    return ApiEnvelope(data=data)


@router.get("", response_model=ApiEnvelope[LedgerLinkResponse])
async def get_ledger_link(
    fields: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[LedgerLinkResponse]:
    if fields is not None and fields not in _ALLOWED_FIELDS:
        raise HTTPException(400, f"Invalid fields: {fields}")
    data = await build_ledger_link(db, tenant_id=ctx.tenant_id, fields=fields)
    return ApiEnvelope(data=data)
