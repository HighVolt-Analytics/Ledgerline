"""Dossier hero view — list and detail for posting bundles."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.matrix import _payments_for_invoices
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.schemas.dossier import DossierSummaryResponse
from app.services.dossier_audit import (
    fetch_dossier_audit_logs,
    fetch_dossier_audit_logs_for_invoices,
)
from app.services.dossier_service import (
    build_dossier_summary,
    list_dossier_invoices,
    org_display_name,
    resolve_invoice_for_dossier,
)
from app.services.invoice_evaluation_service import load_posting_config_for_tenant

router = APIRouter(prefix="/dossiers", tags=["dossiers"])


@router.get("", response_model=ApiEnvelope[list[DossierSummaryResponse]])
async def list_dossiers(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    document_type_code: str | None = Query(None, alias="document_type_code"),
    q: str | None = Query(None, description="Search vendor, ref, PO, document type"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[DossierSummaryResponse]]:
    invoices, total = await list_dossier_invoices(
        db,
        ctx.tenant_id,
        page=page,
        page_size=page_size,
        document_type_code=document_type_code,
        q=q,
    )
    pages = max(1, (total + page_size - 1) // page_size)
    if not invoices:
        return ApiEnvelope(data=[], meta=ResponseMeta(page=page, total=total, pages=pages))

    invoice_ids = [inv.id for inv in invoices]
    audit_by_id, payments_by_id, buyer, config = await _load_dossier_list_context(
        db, ctx.tenant_id, invoice_ids
    )

    data: list[DossierSummaryResponse] = []
    for inv in invoices:
        data.append(
            await build_dossier_summary(
                db,
                inv,
                audit_by_id.get(inv.id, []),
                payment=payments_by_id.get(inv.id),
                tenant_name=buyer,
                compact=True,
                config=config,
            )
        )
    return ApiEnvelope(data=data, meta=ResponseMeta(page=page, total=total, pages=pages))


@router.get("/{dossier_id}", response_model=ApiEnvelope[DossierSummaryResponse])
async def get_dossier(
    dossier_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DossierSummaryResponse]:
    inv = await resolve_invoice_for_dossier(db, ctx.tenant_id, dossier_id)
    if inv is None:
        raise HTTPException(404, "Dossier not found")

    logs, payments, buyer, config = await _load_dossier_detail_context(db, ctx.tenant_id, inv.id)

    return ApiEnvelope(
        data=await build_dossier_summary(
            db,
            inv,
            logs,
            payment=payments.get(inv.id),
            tenant_name=buyer,
            compact=False,
            config=config,
        )
    )


async def _load_dossier_list_context(
    db: AsyncSession,
    tenant_id: int,
    invoice_ids: list[int],
):
    audit_task = fetch_dossier_audit_logs_for_invoices(db, invoice_ids)
    payments_task = _payments_for_invoices(db, tenant_id, invoice_ids)
    buyer_task = org_display_name(db, tenant_id)
    config_task = load_posting_config_for_tenant(db, tenant_id)
    audit_by_id, payments_by_id, buyer, config = await asyncio.gather(
        audit_task,
        payments_task,
        buyer_task,
        config_task,
    )
    return audit_by_id, payments_by_id, buyer, config


async def _load_dossier_detail_context(
    db: AsyncSession,
    tenant_id: int,
    invoice_id: int,
):
    logs_task = fetch_dossier_audit_logs(db, invoice_id)
    payments_task = _payments_for_invoices(db, tenant_id, [invoice_id])
    buyer_task = org_display_name(db, tenant_id)
    config_task = load_posting_config_for_tenant(db, tenant_id)
    logs, payments, buyer, config = await asyncio.gather(
        logs_task,
        payments_task,
        buyer_task,
        config_task,
    )
    return logs, payments, buyer, config
