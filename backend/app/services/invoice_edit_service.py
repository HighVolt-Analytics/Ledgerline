"""Manual field edits for invoices in the approval queue."""

from __future__ import annotations


from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.schemas.invoice import InvoiceUpdateRequest
from app.services.audit_service import log_event

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


async def update_invoice_fields(
    session: AsyncSession,
    inv: Invoice,
    body: InvoiceUpdateRequest,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    if inv.status not in _EDITABLE:
        raise ValueError(
            f"Invoice status '{inv.status.value}' cannot be edited; "
            "only exception, duplicate, or rejected invoices in the review queue"
        )

    payload = body.model_dump(exclude_unset=True)
    line_items_payload = payload.pop("line_items", None)
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

    if not changes:
        return

    await session.flush()
    await log_event(
        session,
        "invoice_fields_updated",
        invoice_id=inv.id,
        detail={"changes": changes},
        actor_name=actor_name,
        actor_email=actor_email,
    )
