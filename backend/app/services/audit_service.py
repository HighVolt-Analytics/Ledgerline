"""Audit log helpers — actor attribution on human actions."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.utils.logger import correlation_id_ctx, get_logger

logger = get_logger(__name__)


def merge_actor_detail(
    detail: dict[str, Any] | None,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> dict[str, Any] | None:
    if not actor_name and not actor_email:
        return detail
    merged = dict(detail or {})
    if actor_name:
        merged["actor_name"] = actor_name
    if actor_email:
        merged["actor_email"] = actor_email
    return merged


async def log_event(
    session: AsyncSession,
    event: str,
    *,
    invoice_id: int | None = None,
    tenant_id: uuid.UUID | int | None = None,
    detail: dict[str, Any] | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
    client_ip: str | None = None,
) -> AuditLog:
    from app.models.invoice import Invoice
    from app.services.audit_detail_helpers import invoice_snapshot_detail

    resolved_tenant_id = tenant_id
    invoice_for_snapshot: Invoice | None = None
    if invoice_id is not None:
        if resolved_tenant_id is not None:
            from app.tenant_scoped import get_for_tenant

            invoice_for_snapshot = await get_for_tenant(
                session, Invoice, invoice_id, resolved_tenant_id
            )
        else:
            invoice_for_snapshot = await session.get(Invoice, invoice_id)
            if invoice_for_snapshot is not None and resolved_tenant_id is None:
                resolved_tenant_id = invoice_for_snapshot.tenant_id

    merged_detail = merge_actor_detail(
        detail,
        actor_name=actor_name,
        actor_email=actor_email,
    )
    if invoice_for_snapshot is not None:
        merged_detail = dict(merged_detail or {})
        snapshot = invoice_snapshot_detail(invoice_for_snapshot)
        for key, value in snapshot.items():
            merged_detail.setdefault(key, value)
    if client_ip:
        merged_detail = dict(merged_detail or {})
        merged_detail["client_ip"] = client_ip
    if resolved_tenant_id is not None:
        merged_detail = dict(merged_detail or {})
        merged_detail.setdefault("tenant_id", str(resolved_tenant_id))

    entry = AuditLog(
        event=event,
        tenant_id=resolved_tenant_id,
        invoice_id=invoice_id,
        correlation_id=correlation_id_ctx.get(),
        detail=merged_detail,
    )
    session.add(entry)
    await session.flush()
    logger.info(
        "audit",
        event_name=event,
        invoice_id=invoice_id,
        actor_name=actor_name,
    )
    return entry


async def audit_logs_for_invoices(
    session: AsyncSession,
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID | int | None = None,
) -> dict[int, list[AuditLog]]:
    """Batch-load audit logs grouped by invoice id (newest first per invoice)."""
    if not invoice_ids:
        return {}
    from sqlalchemy import select

    from app.tenant_scoped import coerce_tenant_uuid

    stmt = (
        select(AuditLog)
        .where(AuditLog.invoice_id.in_(invoice_ids))
        .order_by(AuditLog.created_at.desc())
    )
    tid = coerce_tenant_uuid(tenant_id)
    if tid is not None:
        stmt = stmt.where(AuditLog.tenant_id == tid)
    rows = (await session.execute(stmt)).scalars().all()
    grouped: dict[int, list[AuditLog]] = {invoice_id: [] for invoice_id in invoice_ids}
    for row in rows:
        if row.invoice_id is not None:
            grouped.setdefault(row.invoice_id, []).append(row)
    return grouped
