"""Shared invoice-related queries for matrix, dossiers, and API layers."""

from __future__ import annotations

import uuid

from typing import Collection

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.payment import Payment


async def audit_logs_for_invoice_ids(
    db: AsyncSession,
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID,
    per_invoice_limit: int | None = None,
    events: Collection[str] | None = None,
) -> dict[int, list[AuditLog]]:
    """Load audit logs for many invoices.

    When ``per_invoice_limit`` is set, only the newest N rows per invoice are
    returned (windowed). Matrix list uses this so page_size=100 does not pull
    unbounded audit history into API memory.
    """
    if not invoice_ids:
        return {}
    filters = [
        AuditLog.invoice_id.in_(invoice_ids),
        AuditLog.tenant_id == tenant_id,
    ]
    if events:
        filters.append(AuditLog.event.in_(tuple(events)))
    if per_invoice_limit is None or per_invoice_limit <= 0:
        rows = (
            await db.execute(
                select(AuditLog)
                .where(*filters)
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().all()
    else:
        ranked = (
            select(
                AuditLog.id.label("audit_id"),
                func.row_number()
                .over(
                    partition_by=AuditLog.invoice_id,
                    order_by=AuditLog.created_at.desc(),
                )
                .label("rn"),
            )
            .where(*filters)
            .subquery()
        )
        rows = (
            await db.execute(
                select(AuditLog)
                .join(ranked, AuditLog.id == ranked.c.audit_id)
                .where(ranked.c.rn <= per_invoice_limit)
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().all()
    grouped: dict[int, list[AuditLog]] = {i: [] for i in invoice_ids}
    for row in rows:
        if row.invoice_id is not None:
            grouped.setdefault(row.invoice_id, []).append(row)
    return grouped


async def payments_for_invoice_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice_ids: list[int],
) -> dict[int, Payment]:
    if not invoice_ids:
        return {}
    rows = (
        await db.execute(
            select(Payment).where(
                Payment.tenant_id == tenant_id,
                Payment.invoice_id.in_(invoice_ids),
            )
        )
    ).scalars().all()
    return {row.invoice_id: row for row in rows}
