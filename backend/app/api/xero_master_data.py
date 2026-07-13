"""Tenant-scoped Xero master-data and sync-history read APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.xero_master_data import (
    XeroAccountsResponse,
    XeroContactsResponse,
    XeroExportHistoryResponse,
    XeroMasterTotals,
    XeroReconcileRequest,
    XeroReconcileResponse,
    XeroSyncHistoryResponse,
    XeroTaxRatesResponse,
)
from app.services.integration.xero_client import XeroApiError
from app.services.integration.xero_master_data_service import (
    get_master_data_totals,
    list_export_history,
    list_sync_history,
    list_xero_accounts,
    list_xero_contacts,
    list_xero_tax_rates,
)
from app.services.integration.xero_reconcile_service import reconcile_pending

router = APIRouter(prefix="/integrations/xero", tags=["accounting-integrations"])


@router.get("/accounts", response_model=ApiEnvelope[XeroAccountsResponse])
async def xero_accounts(
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroAccountsResponse]:
    data = await list_xero_accounts(
        db,
        tenant_id=ctx.tenant_id,
        search=search,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ApiEnvelope(data=XeroAccountsResponse.model_validate(data))


@router.get("/tax-rates", response_model=ApiEnvelope[XeroTaxRatesResponse])
async def xero_tax_rates(
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroTaxRatesResponse]:
    data = await list_xero_tax_rates(
        db,
        tenant_id=ctx.tenant_id,
        search=search,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ApiEnvelope(data=XeroTaxRatesResponse.model_validate(data))


@router.get("/contacts", response_model=ApiEnvelope[XeroContactsResponse])
async def xero_contacts(
    search: str | None = Query(None),
    status: str | None = Query(None),
    mapping_status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroContactsResponse]:
    data = await list_xero_contacts(
        db,
        tenant_id=ctx.tenant_id,
        search=search,
        status=status,
        mapping_status=mapping_status,
        limit=limit,
        offset=offset,
    )
    return ApiEnvelope(data=XeroContactsResponse.model_validate(data))


@router.get("/sync-history", response_model=ApiEnvelope[XeroSyncHistoryResponse])
async def xero_sync_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroSyncHistoryResponse]:
    data = await list_sync_history(
        db,
        tenant_id=ctx.tenant_id,
        limit=limit,
        offset=offset,
    )
    return ApiEnvelope(data=XeroSyncHistoryResponse.model_validate(data))


@router.get("/export-history", response_model=ApiEnvelope[XeroExportHistoryResponse])
async def xero_export_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroExportHistoryResponse]:
    data = await list_export_history(
        db,
        tenant_id=ctx.tenant_id,
        limit=limit,
        offset=offset,
    )
    return ApiEnvelope(data=XeroExportHistoryResponse.model_validate(data))


@router.get("/master-totals", response_model=ApiEnvelope[XeroMasterTotals])
async def xero_master_totals(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroMasterTotals]:
    data = await get_master_data_totals(db, ctx.tenant_id)
    return ApiEnvelope(data=XeroMasterTotals.model_validate(data))


@router.post("/reconcile", response_model=ApiEnvelope[XeroReconcileResponse])
async def xero_reconcile(
    body: XeroReconcileRequest | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroReconcileResponse]:
    try:
        result = await reconcile_pending(
            db,
            tenant_id=ctx.tenant_id,
            ref_id=body.ref_id if body else None,
            trigger_type="manual",
            initiated_by=ctx.user_id,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except XeroApiError as exc:
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await db.commit()
    result["committed"] = True
    return ApiEnvelope(data=XeroReconcileResponse.model_validate(result))
