"""Audit log helpers for dossier read paths."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.services.dossier.dossier_pipeline_service import PIPELINE_AUDIT_EVENTS
from app.services.invoice.processing_cycle_service import CYCLE_RESET_EVENTS

# Pipeline stage events plus cycle-reset markers (so _cycle_logs ignores stale approvals)
# and early-abort pipeline_error surfaced on the dossier timeline.
DOSSIER_AUDIT_EVENTS: frozenset[str] = (
    PIPELINE_AUDIT_EVENTS | CYCLE_RESET_EVENTS | frozenset({"pipeline_error"})
)


async def fetch_dossier_audit_logs(
    session: AsyncSession,
    invoice_id: int,
) -> list[AuditLog]:
    """Load only audit events needed to render dossier pipeline + approval."""
    return list(
        (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == invoice_id,
                    AuditLog.event.in_(DOSSIER_AUDIT_EVENTS),
                )
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().all()
    )


async def fetch_dossier_audit_logs_for_invoices(
    session: AsyncSession,
    invoice_ids: list[int],
) -> dict[int, list[AuditLog]]:
    if not invoice_ids:
        return {}
    rows = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.event.in_(DOSSIER_AUDIT_EVENTS),
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()
    grouped: dict[int, list[AuditLog]] = {i: [] for i in invoice_ids}
    for row in rows:
        if row.invoice_id is not None:
            grouped.setdefault(row.invoice_id, []).append(row)
    return grouped
