"""Re-apply rule book GL mapping and routing evaluation to existing invoices."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice_evaluation_service import apply_invoice_evaluation
from app.services.rule_book_mapper import map_invoice_to_account

_REMAP_SKIP = frozenset(
    {
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)

@dataclass(frozen=True)
class RemapResult:
    updated: int
    invoice_ids: list[int]
    total: int


async def remap_invoices_for_org(session: AsyncSession, *, org_id: int) -> RemapResult:
    """Update account mapping and routing fields from current rule book."""
    rows = (
        await session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(
                Invoice.org_id == org_id,
                Invoice.status.not_in(_REMAP_SKIP),
            )
        )
    ).scalars().all()

    updated = 0
    changed_ids: list[int] = []
    for inv in rows:
        mapping = map_invoice_to_account(inv)
        changed = False
        if (
            inv.account_code != mapping.account_code
            or inv.account_name != mapping.account_name
        ):
            inv.account_code = mapping.account_code
            inv.account_name = mapping.account_name
            changed = True

        before = (
            inv.route_target,
            inv.matched_rule_ids,
            inv.vendor_confidence,
            inv.evaluation_status,
        )
        await apply_invoice_evaluation(session, inv, enqueue_pending=False)
        after = (
            inv.route_target,
            inv.matched_rule_ids,
            inv.vendor_confidence,
            inv.evaluation_status,
        )
        if before != after:
            changed = True

        if changed:
            updated += 1
            changed_ids.append(inv.id)

    await session.flush()
    return RemapResult(updated=updated, invoice_ids=changed_ids, total=len(rows))
