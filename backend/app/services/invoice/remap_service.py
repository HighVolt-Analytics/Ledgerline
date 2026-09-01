"""Re-apply rule book GL mapping and routing evaluation to existing invoices."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import db_session_with_rls
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.audit.audit_service import log_event
from app.services.invoice.invoice_evaluation_service import apply_invoice_evaluation, load_config_for_tenant
from app.services.classification.document_type_reclassify_service import reclassify_invoice_document_type
from app.services.payments.journal_generator import (
    generate_entries,
    get_unresolved_control_accounts,
    is_balanced,
)
from app.services.payments.journal_persist_service import persist_journal_lines
from app.services.payments.fiscal_period_service import PeriodClosedError
from app.services.master_data.journal_counterparty_resolver import (
    resolve_counterparty_registry_ids_for_journal,
)
from app.services.master_data.party_coa_subledger_service import resolve_invoice_control_mapping
from app.services.rule_book.account_mapper import resolve_fallback_account_mapping
from app.services.rule_book.rule_book_mapper import map_invoice_to_account
from app.tenant_child_tables import journal_entries_for_invoice
from app.services.vault.vault_blob_sync import sync_invoice_blob_path
from app.utils.logger import get_logger

logger = get_logger(__name__)

_REMAP_SKIP = frozenset(
    {
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)

_JOURNAL_REGEN_STATUSES = frozenset(
    {
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
        InvoiceStatus.PROCESSED,
    }
)


@dataclass(frozen=True)
class RemapResult:
    updated: int
    invoice_ids: list[int]
    total: int
    journals_regenerated: int


async def _regenerate_journal_entries(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
) -> bool:
    journal_count = (
        await session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(invoice.tenant_id, invoice.id))
        )
    ).scalar() or 0
    if journal_count == 0:
        return False

    mapping = map_invoice_to_account(invoice, config=config)
    vendor_reg_id, customer_reg_id = await resolve_counterparty_registry_ids_for_journal(
        session, invoice
    )
    control_mapping = await resolve_invoice_control_mapping(
        session,
        invoice,
        config,
        vendor_registry_id=vendor_reg_id,
        customer_registry_id=customer_reg_id,
    )
    from app.models.tenant import Tenant
    from app.tenant_settings import tenant_currency
    from app.services.purchase.team_expense_advance_service import (
        resolve_claim_advance_available,
    )

    tenant = await session.get(Tenant, invoice.tenant_id)
    base_currency = tenant_currency(tenant)
    lines = generate_entries(
        invoice,
        mapping,
        config=config,
        vendor_registry_id=vendor_reg_id,
        customer_registry_id=customer_reg_id,
        control_mapping=control_mapping,
        base_currency=base_currency,
        advance_available=await resolve_claim_advance_available(
            session, invoice, config
        ),
    )
    # Remap skips keep PROCESSED status; audit log (context=remap_skip) is the trail —
    # Pipeline debug journal step only fails when status is EXCEPTION.
    if not is_balanced(lines):
        logger.warning(
            "remap_journal_regen_skipped_unbalanced",
            invoice_id=invoice.id,
            tenant_id=str(invoice.tenant_id),
        )
        await log_event(
            session,
            "journal_unbalanced",
            invoice_id=invoice.id,
            detail={
                "subtotal": float(invoice.subtotal or 0),
                "gst": float(invoice.gst or 0),
                "total": float(invoice.total or 0),
                "context": "remap_skip",
            },
        )
        return False

    unresolved_control = get_unresolved_control_accounts(invoice=invoice, config=config)
    if unresolved_control:
        fallback = resolve_fallback_account_mapping(config)
        logger.warning(
            "remap_journal_regen_skipped_unresolved_control",
            invoice_id=invoice.id,
            tenant_id=str(invoice.tenant_id),
        )
        await log_event(
            session,
            "journal_control_account_unresolved",
            invoice_id=invoice.id,
            detail={
                "unresolved": unresolved_control,
                "fallback_code": fallback.account_code,
                "fallback_name": fallback.account_name,
                "route_target": invoice.route_target,
                "context": "remap_skip",
            },
        )
        return False

    # Only replace accrual lines — preserve payment/collection settlements.
    from app.services.payments.journal_reversal_service import reverse_invoice_accrual_batches

    await reverse_invoice_accrual_batches(
        session,
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        reason="remap_regenerate",
    )

    try:
        await persist_journal_lines(session, invoice, lines, base_currency=base_currency)
    except PeriodClosedError:
        logger.warning(
            "remap_journal_regen_skipped_period_closed",
            invoice_id=invoice.id,
            tenant_id=str(invoice.tenant_id),
        )
        await log_event(
            session,
            "journal_period_closed",
            invoice_id=invoice.id,
            detail={"context": "remap_skip"},
        )
        return False
    return True


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
    journals_regenerated = 0
    config = await load_config_for_tenant(session, tenant_id)
    for inv in rows:
        mapping = map_invoice_to_account(inv, config=config)
        changed = False
        mapping_changed = False
        # Capture before reclassify: that path also calls apply_invoice_evaluation
        # and can flip auto_coded → needs_review before the guard below runs.
        prior_eval = (inv.evaluation_status or "").strip()
        if await reclassify_invoice_document_type(session, inv, config=config):
            changed = True
        if (
            inv.account_code != mapping.account_code
            or inv.account_name != mapping.account_name
        ):
            inv.account_code = mapping.account_code
            inv.account_name = mapping.account_name
            changed = True
            mapping_changed = True

        before = (
            inv.route_target,
            inv.matched_rule_ids,
            inv.vendor_confidence,
            inv.evaluation_status,
        )
        await apply_invoice_evaluation(session, inv, config=config, enqueue_pending=False)
        # Posted invoices are terminal for coding review: a rule-book change must
        # not flip them back to needs_review with no gate to clear it. Recoding a
        # posted document goes through the explicit reset/approval flow instead.
        # Approval / awaiting-PO|SO holds are sticky inside apply_invoice_evaluation.
        if (
            inv.status == InvoiceStatus.PROCESSED
            and (inv.evaluation_status or "").strip() == "needs_review"
            and prior_eval
            and prior_eval != "needs_review"
        ):
            inv.evaluation_status = prior_eval
        after = (
            inv.route_target,
            inv.matched_rule_ids,
            inv.vendor_confidence,
            inv.evaluation_status,
        )
        if before != after:
            changed = True

        if mapping_changed and inv.status in _JOURNAL_REGEN_STATUSES:
            if await _regenerate_journal_entries(session, inv, config=config):
                journals_regenerated += 1
                changed = True

        if changed:
            try:
                await sync_invoice_blob_path(session, inv, parsed_vendor=inv.vendor)
            except Exception as exc:
                logger.warning(
                    "remap_blob_relocate_skipped",
                    tenant_id=str(tenant_id),
                    invoice_id=inv.id,
                    error=str(exc),
                )
            updated += 1
            changed_ids.append(inv.id)

    return RemapResult(
        updated=updated,
        invoice_ids=changed_ids,
        total=len(rows),
        journals_regenerated=journals_regenerated,
    )


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
                        "journals_regenerated": result.journals_regenerated,
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
