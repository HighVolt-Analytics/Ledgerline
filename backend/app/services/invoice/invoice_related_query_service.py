"""Shared invoice-related queries for matrix, dossiers, and API layers."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.payment import Payment


async def audit_logs_for_invoice_ids(
    db: AsyncSession,
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID,
) -> dict[int, list[AuditLog]]:
    if not invoice_ids:
        return {}
    rows = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.tenant_id == tenant_id,
            )
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
