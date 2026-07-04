"""Dossier list and detail API orchestration."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.common import ResponseMeta
from app.schemas.dossier import DossierSummaryResponse
from app.schemas.dossier_api import DossierListRequest
from app.services.dossier.dossier_audit import (
    fetch_dossier_audit_logs,
    fetch_dossier_audit_logs_for_invoices,
)
from app.services.dossier.dossier_service import (
    build_dossier_summary,
    list_dossier_invoices,
    org_display_name,
    resolve_invoice_for_dossier,
)
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.invoice.invoice_related_query_service import payments_for_invoice_ids


async def load_dossier_list_context(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice_ids: list[int],
):
    audit_task = fetch_dossier_audit_logs_for_invoices(db, invoice_ids)
    payments_task = payments_for_invoice_ids(db, tenant_id, invoice_ids)
    buyer_task = org_display_name(db, tenant_id)
    config_task = load_posting_config_for_tenant(db, tenant_id)
    return await asyncio.gather(audit_task, payments_task, buyer_task, config_task)


async def load_dossier_detail_context(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice_id: int,
):
    logs_task = fetch_dossier_audit_logs(db, invoice_id)
    payments_task = payments_for_invoice_ids(db, tenant_id, [invoice_id])
    buyer_task = org_display_name(db, tenant_id)
    config_task = load_posting_config_for_tenant(db, tenant_id)
    return await asyncio.gather(logs_task, payments_task, buyer_task, config_task)


async def build_dossier_detail_summary(
    db: AsyncSession,
    inv: Invoice,
    *,
    tenant_id: uuid.UUID,
    compact: bool,
) -> DossierSummaryResponse:
    logs, payments, buyer, config = await load_dossier_detail_context(
        db, tenant_id, inv.id
    )
    return await build_dossier_summary(
        db,
        inv,
        logs,
        payment=payments.get(inv.id),
        tenant_name=buyer,
        compact=compact,
        config=config,
    )


async def list_dossier_summaries(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: DossierListRequest,
) -> tuple[list[DossierSummaryResponse], ResponseMeta]:
    invoices, total = await list_dossier_invoices(
        db,
        tenant_id,
        page=params.page,
        page_size=params.page_size,
        document_type_code=params.document_type_code,
        q=params.q,
    )
    pages = max(1, (total + params.page_size - 1) // params.page_size)
    meta = ResponseMeta(page=params.page, total=total, pages=pages)
    if not invoices:
        return [], meta

    invoice_ids = [inv.id for inv in invoices]
    audit_by_id, payments_by_id, buyer, config = await load_dossier_list_context(
        db, tenant_id, invoice_ids
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
    return data, meta


async def get_dossier_by_id(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    dossier_id: str,
) -> DossierSummaryResponse | None:
    inv = await resolve_invoice_for_dossier(db, tenant_id, dossier_id)
    if inv is None:
        return None
    return await build_dossier_detail_summary(
        db, inv, tenant_id=tenant_id, compact=False
    )
