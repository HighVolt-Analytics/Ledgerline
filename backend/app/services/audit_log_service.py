"""Audit log listing and export orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice
from app.schemas.audit import AuditLogExportRequest, AuditLogListRequest
from app.services.audit_export_service import (
    audit_rows_to_csv,
    fetch_audit_rows_for_export,
    resolve_audit_export_range,
)
from app.tenant_scoped import get_for_tenant


@dataclass(frozen=True)
class AuditLogListResult:
    rows: list[AuditLog]
    page: int
    total: int
    pages: int


@dataclass(frozen=True)
class AuditExportPayload:
    csv_text: str
    filename: str


async def assert_invoice_in_tenant(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> None:
    inv = await get_for_tenant(db, Invoice, invoice_id, tenant_id)
    if not inv:
        raise LookupError("Invoice not found")


def _tenant_audit_filter(tenant_id: uuid.UUID):
    return or_(
        AuditLog.tenant_id == tenant_id,
        AuditLog.invoice_id.in_(
            select(Invoice.id).where(Invoice.tenant_id == tenant_id)
        ),
    )


async def list_audit_logs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: AuditLogListRequest,
) -> AuditLogListResult:
    if params.invoice_id is not None:
        await assert_invoice_in_tenant(
            db, tenant_id=tenant_id, invoice_id=params.invoice_id
        )

    org_filter = _tenant_audit_filter(tenant_id)
    stmt = select(AuditLog).where(org_filter).order_by(AuditLog.created_at.desc())
    count_stmt = select(func.count(AuditLog.id)).where(org_filter)

    if params.invoice_id is not None:
        stmt = stmt.where(AuditLog.invoice_id == params.invoice_id)
        count_stmt = count_stmt.where(AuditLog.invoice_id == params.invoice_id)
    if params.event:
        stmt = stmt.where(AuditLog.event == params.event)
        count_stmt = count_stmt.where(AuditLog.event == params.event)

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + params.page_size - 1) // params.page_size)
    rows = (
        await db.execute(
            stmt.offset((params.page - 1) * params.page_size).limit(params.page_size)
        )
    ).scalars().all()

    return AuditLogListResult(
        rows=list(rows),
        page=params.page,
        total=total,
        pages=pages,
    )


def audit_export_filename(
    *,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
) -> str:
    if month:
        return f"audit_log_{month}.csv"
    if date_from and date_to and date_from == date_to:
        return f"audit_log_{date_from.isoformat()}.csv"
    if date_from and date_to:
        return f"audit_log_{date_from.isoformat()}_to_{date_to.isoformat()}.csv"
    if date_from:
        return f"audit_log_from_{date_from.isoformat()}.csv"
    if date_to:
        return f"audit_log_to_{date_to.isoformat()}.csv"
    return "audit_log.csv"


async def build_audit_export(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: AuditLogExportRequest,
) -> AuditExportPayload:
    date_from, date_to = resolve_audit_export_range(
        month=params.month,
        date_from=params.date_from,
        date_to=params.date_to,
    )

    rows, invoice_map, purchase_by_po_id, purchase_by_po_number, linked_docs = (
        await fetch_audit_rows_for_export(
            db,
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            document_only=params.document_only,
            dedupe=params.dedupe,
        )
    )
    csv_text = audit_rows_to_csv(
        rows,
        invoice_map=invoice_map,
        purchase_vault_by_po_id=purchase_by_po_id,
        purchase_vault_by_po_number=purchase_by_po_number,
        linked_docs_by_invoice=linked_docs,
    )
    filename = audit_export_filename(
        month=params.month,
        date_from=date_from,
        date_to=date_to,
    )
    return AuditExportPayload(csv_text=csv_text, filename=filename)
