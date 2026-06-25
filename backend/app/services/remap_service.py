"""Re-apply rule book GL mapping and routing evaluation to existing invoices."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import db_session_with_rls
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit_service import log_event
from app.services.invoice_evaluation_service import apply_invoice_evaluation, load_config_for_tenant
from app.services.document_type_reclassify_service import reclassify_invoice_document_type
from app.services.rule_book_mapper import map_invoice_to_account
from app.services.vault_blob_sync import sync_invoice_blob_path
from app.utils.logger import get_logger

logger = get_logger(__name__)

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


async def remap_invoices_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> RemapResult:
    """Update account mapping and routing fields from current rule book."""
    rows = (
        await session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status.not_in(_REMAP_SKIP),
            )
        )
    ).scalars().all()

    updated = 0
    changed_ids: list[int] = []
    config = await load_config_for_tenant(session, tenant_id)
    for inv in rows:
        mapping = map_invoice_to_account(inv, config=config)
        changed = False
        if await reclassify_invoice_document_type(session, inv, config=config):
            changed = True
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
        await apply_invoice_evaluation(session, inv, config=config, enqueue_pending=False)
        after = (
            inv.route_target,
            inv.matched_rule_ids,
            inv.vendor_confidence,
            inv.evaluation_status,
        )
        if before != after:
            changed = True

        if changed:
            await sync_invoice_blob_path(session, inv, parsed_vendor=inv.vendor)
            updated += 1
            changed_ids.append(inv.id)

    return RemapResult(updated=updated, invoice_ids=changed_ids, total=len(rows))


async def remap_tenant_invoices_background(
    tenant_id: uuid.UUID,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
    client_ip: str | None = None,
) -> None:
    """Run invoice remap outside the request path (catalogue deletes, etc.)."""
    try:
        async with db_session_with_rls(tenant_id) as session:
            result = await remap_invoices_for_tenant(session, tenant_id=tenant_id)
            if result.updated:
                await log_event(
                    session,
                    "invoices_remapped",
                    tenant_id=tenant_id,
                    detail={
                        "updated": result.updated,
                        "total": result.total,
                        "invoice_ids": result.invoice_ids[:200],
                        "invoice_ids_truncated": len(result.invoice_ids) > 200,
                    },
                    actor_name=actor_name,
                    actor_email=actor_email,
                    client_ip=client_ip,
                )
    except Exception:
        logger.exception(
            "remap_tenant_invoices_background_failed",
            tenant_id=str(tenant_id),
        )
