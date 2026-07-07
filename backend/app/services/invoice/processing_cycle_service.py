"""Processing-cycle boundaries for audit-scoped pipeline state."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

CYCLE_RESET_EVENTS: frozenset[str] = frozenset(
    {
        "invoice_rejected",
        "invoice_requeued",
        "duplicate_reingest_rejected",
    }
)


def latest_cycle_reset_log_id_from_logs(logs: list[AuditLog]) -> int:
    """Max audit log id for cycle-reset events in an in-memory log list."""
    return max(
        (log.id for log in logs if log.event in CYCLE_RESET_EVENTS),
        default=0,
    )


async def latest_cycle_reset_log_id(
    session: AsyncSession,
    invoice_id: int,
    *,
    tenant_id: uuid.UUID | None = None,
) -> int:
    """Most recent event that starts a fresh pipeline cycle for this invoice."""
    filters = [
        AuditLog.invoice_id == invoice_id,
        AuditLog.event.in_(CYCLE_RESET_EVENTS),
    ]
    if tenant_id is not None:
        filters.append(AuditLog.tenant_id == tenant_id)
    row = (
        await session.execute(select(func.max(AuditLog.id)).where(*filters))
    ).scalar_one_or_none()
    return int(row or 0)


async def has_audit_event_after_cycle_reset(
    session: AsyncSession,
    invoice_id: int,
    *,
    event: str,
    tenant_id: uuid.UUID | None = None,
) -> bool:
    """True when ``event`` was logged after the latest cycle reset."""
    reset_id = await latest_cycle_reset_log_id(
        session,
        invoice_id,
        tenant_id=tenant_id,
    )
    filters = [
        AuditLog.invoice_id == invoice_id,
        AuditLog.event == event,
        AuditLog.id > reset_id,
    ]
    if tenant_id is not None:
        filters.append(AuditLog.tenant_id == tenant_id)
    row = (
        await session.execute(select(AuditLog.id).where(*filters).limit(1))
    ).scalar_one_or_none()
    return row is not None


async def latest_audit_detail_after_cycle_reset(
    session: AsyncSession,
    invoice_id: int,
    *,
    event: str,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, object] | None:
    """Latest audit detail for ``event`` after the most recent cycle reset."""
    reset_id = await latest_cycle_reset_log_id(
        session,
        invoice_id,
        tenant_id=tenant_id,
    )
    filters = [
        AuditLog.invoice_id == invoice_id,
        AuditLog.event == event,
        AuditLog.id > reset_id,
    ]
    if tenant_id is not None:
        filters.append(AuditLog.tenant_id == tenant_id)
    row = (
        await session.execute(
            select(AuditLog).where(*filters).order_by(AuditLog.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if row is None or not isinstance(row.detail, dict):
        return None
    return row.detail
