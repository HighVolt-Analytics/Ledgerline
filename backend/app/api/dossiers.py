"""Dossier hero view — list and detail for posting bundles."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.dossier import DossierManualLinkCreateRequest, DossierSummaryResponse
from app.schemas.dossier_api import DossierListRequest
from app.services.dossier.dossier_api_service import (
    build_dossier_detail_summary,
    get_dossier_by_id,
    list_dossier_summaries,
)
from app.services.dossier.dossier_manual_link_service import create_manual_link, delete_manual_link
from app.services.dossier.dossier_service import resolve_invoice_for_dossier

router = APIRouter(prefix="/dossiers", tags=["dossiers"])


@router.get("", response_model=ApiEnvelope[list[DossierSummaryResponse]])
async def list_dossiers(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 12,
    document_type_code: Annotated[str | None, Query()] = None,
    q: Annotated[
        str | None, Query(description="Search vendor, ref, PO, document type")
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[DossierSummaryResponse]]:
    params = DossierListRequest(
        page=page,
        page_size=page_size,
        document_type_code=document_type_code,
        q=q,
    )
    data, meta = await list_dossier_summaries(db, tenant_id=ctx.tenant_id, params=params)
    return ApiEnvelope(data=data, meta=meta)


@router.get("/{dossier_id}", response_model=ApiEnvelope[DossierSummaryResponse])
async def get_dossier(
    dossier_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DossierSummaryResponse]:
    summary = await get_dossier_by_id(db, tenant_id=ctx.tenant_id, dossier_id=dossier_id)
    if summary is None:
        raise HTTPException(404, "Dossier not found")
    return ApiEnvelope(data=summary)


@router.post("/{dossier_id}/manual-links", response_model=ApiEnvelope[DossierSummaryResponse])
async def add_dossier_manual_link(
    dossier_id: str,
    body: DossierManualLinkCreateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DossierSummaryResponse]:
    inv = await resolve_invoice_for_dossier(db, ctx.tenant_id, dossier_id)
    if inv is None:
        raise HTTPException(404, "Dossier not found")

    await create_manual_link(
        db,
        tenant_id=ctx.tenant_id,
        anchor_invoice_id=inv.id,
        linked_invoice_id=body.linked_invoice_id,
        slot_id=body.slot_id,
        created_by_user_id=ctx.user_id,
    )
    # Do not commit mid-request: set_config(..., is_local=true) RLS would reset,
    # and invoices use FORCE ROW LEVEL SECURITY. get_db commits after the response.

    return ApiEnvelope(
        data=await build_dossier_detail_summary(
            db, inv, tenant_id=ctx.tenant_id, compact=False
        )
    )


@router.delete("/{dossier_id}/manual-links/{link_id}", response_model=ApiEnvelope[DossierSummaryResponse])
async def remove_dossier_manual_link(
    dossier_id: str,
    link_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DossierSummaryResponse]:
    inv = await resolve_invoice_for_dossier(db, ctx.tenant_id, dossier_id)
    if inv is None:
        raise HTTPException(404, "Dossier not found")

    removed = await delete_manual_link(
        db,
        tenant_id=ctx.tenant_id,
        anchor_invoice_id=inv.id,
        link_id=link_id,
    )
    if not removed:
        raise HTTPException(404, "Manual link not found")

    return ApiEnvelope(
        data=await build_dossier_detail_summary(
            db, inv, tenant_id=ctx.tenant_id, compact=False
        )
    )
