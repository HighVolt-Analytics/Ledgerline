"""Recover PENDING invoices whose pipeline enqueue was lost."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus


async def find_stuck_pending_invoice_ids(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    stale_after_seconds: int,
    limit: int,
) -> list[int]:
    """PENDING rows with a stored file and no recent audit activity.

    Mail poll intentionally skips the pending sweep (``skip_pending_check=True``),
    so a missed Celery publish leaves invoices pending forever. This finder is the
    application-wide safety net for that gap.
    """
    if stale_after_seconds < 1 or limit < 1:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    latest_audit = (
        select(
            AuditLog.invoice_id.label("invoice_id"),
            func.max(AuditLog.created_at).label("last_at"),
        )
        .where(AuditLog.tenant_id == tenant_id)
        .group_by(AuditLog.invoice_id)
        .subquery()
    )
    stmt = (
        select(Invoice.id)
        .outerjoin(latest_audit, latest_audit.c.invoice_id == Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == InvoiceStatus.PENDING,
            Invoice.raw_file_path.is_not(None),
            Invoice.raw_file_path != "",
            func.coalesce(latest_audit.c.last_at, Invoice.created_at) < cutoff,
        )
        .order_by(Invoice.id.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
