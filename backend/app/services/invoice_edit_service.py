"""Manual field edits for invoices in the approval queue."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.schemas.invoice import InvoiceUpdateRequest
from app.services.audit_service import log_event
from app.services.processing_override_catalog import (
    normalise_processing_overrides,
    serialise_processing_overrides,
    validate_skip_steps,
)

_EDITABLE = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)


def _serialise(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


async def refresh_invoice_evaluation_after_edit(
    session: AsyncSession,
    inv: Invoice,
    *,
    enqueue_pending: bool = True,
) -> None:
    """Re-run routing/vendor evaluation after clerk field corrections."""
    from app.services.invoice_evaluation_service import (
        apply_invoice_evaluation,
        load_config_for_tenant,
    )

    config = await load_config_for_tenant(session, inv.tenant_id)
    await apply_invoice_evaluation(
        session,
        inv,
        config=config,
        enqueue_pending=enqueue_pending,
    )


async def update_invoice_fields(
    session: AsyncSession,
    inv: Invoice,
    body: InvoiceUpdateRequest,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> bool:
    if inv.status not in _EDITABLE:
        raise ValueError(
            f"Invoice status '{inv.status.value}' cannot be edited; "
            "only exception, duplicate, or rejected invoices in the review queue"
        )

    payload = body.model_dump(exclude_unset=True)
    line_items_payload = payload.pop("line_items", None)
    overrides_payload = payload.pop("processing_overrides", None)
    changes: dict[str, dict[str, str | None]] = {}

    for field, value in payload.items():
        old = getattr(inv, field)
        if old != value:
            changes[field] = {"from": _serialise(old), "to": _serialise(value)}
            setattr(inv, field, value)

    if line_items_payload is not None:
        old_count = len(inv.line_items)
        for li in list(inv.line_items):
            await session.delete(li)
        await session.flush()

        for item in line_items_payload:
            session.add(
                LineItem(
                    tenant_id=inv.tenant_id,
                    invoice_id=inv.id,
                    description=item.get("description"),
                    qty=item.get("qty"),
                    unit_price=item.get("unit_price"),
                    amount=item.get("amount"),
                    tax_amount=item.get("tax_amount"),
                )
            )
        changes["line_items"] = {
            "from": str(old_count),
            "to": str(len(line_items_payload)),
        }

    if overrides_payload is not None:
        skip_steps = validate_skip_steps(list(overrides_payload.get("skip_steps") or []))
        new_raw = serialise_processing_overrides(skip_steps)
        old_norm = normalise_processing_overrides(inv.processing_overrides)
        new_norm = normalise_processing_overrides(new_raw)
        if old_norm.skip_steps != new_norm.skip_steps:
            inv.processing_overrides = new_raw
            await session.flush()
            await log_event(
                session,
                "processing_overrides_updated",
                invoice_id=inv.id,
                detail={
                    "from": old_norm.skip_steps,
                    "to": new_norm.skip_steps,
                },
                actor_name=actor_name,
                actor_email=actor_email,
            )
            changes["processing_overrides"] = {
                "from": ",".join(old_norm.skip_steps) or None,
                "to": ",".join(new_norm.skip_steps) or None,
            }

    if not changes:
        return False

    await session.flush()
    await log_event(
        session,
        "invoice_fields_updated",
        invoice_id=inv.id,
        detail={"changes": changes},
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return True


async def invoice_has_manual_field_edits(
    session: AsyncSession,
    invoice_id: int,
    *,
    tenant_id: uuid.UUID,
) -> bool:
    """True when a clerk saved field corrections on this invoice."""
    row = (
        await session.execute(
            select(AuditLog.id)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.tenant_id == tenant_id,
                AuditLog.event == "invoice_fields_updated",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None
