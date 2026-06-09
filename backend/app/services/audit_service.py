"""Audit log helpers — actor attribution on human actions."""

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
    org_id: int | None = None,
    detail: dict[str, Any] | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
    client_ip: str | None = None,
) -> AuditLog:
    resolved_org_id = org_id
    if resolved_org_id is None and invoice_id is not None:
        from app.models.invoice import Invoice

        inv = await session.get(Invoice, invoice_id)
        if inv is not None:
            resolved_org_id = inv.org_id

    merged_detail = merge_actor_detail(
        detail,
        actor_name=actor_name,
        actor_email=actor_email,
    )
    if client_ip:
        merged_detail = dict(merged_detail or {})
        merged_detail["client_ip"] = client_ip
    if resolved_org_id is not None:
        merged_detail = dict(merged_detail or {})
        merged_detail.setdefault("org_id", resolved_org_id)

    entry = AuditLog(
        event=event,
        org_id=resolved_org_id,
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
