"""Post-process settlement (payment / collection) with audit when skipped."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry, JournalEntryKind
from app.models.payment import Payment
from app.services.audit.audit_service import log_event
from app.services.integration.collection_service import ensure_receivable_for_invoice
from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
from app.services.payments.journal_generator import is_balanced
from app.services.payments.journal_persist_service import persist_journal_lines
from app.services.payments.payment_service import ensure_payment_for_invoice
from app.services.payments.settlement_journal_service import (
    generate_collection_settlement_entries,
    generate_payment_settlement_entries,
)
from app.services.purchase.purchase_document_service import is_commercial_purchase_invoice
from app.services.rule_book.account_mapper import category_resolved_in_coa
from app.services.sales.sales_document_service import is_commercial_sales_invoice


def payment_skip_reason(invoice: Invoice) -> str | None:
    if not is_commercial_purchase_invoice(invoice):
        return None
    if invoice.status != InvoiceStatus.PROCESSED:
        return "not_processed"
    if not (invoice.vendor or "").strip():
        return "missing_vendor"
    if invoice.total is None or invoice.total <= 0:
        return "missing_or_invalid_total"
    if invoice.due_date is None:
        return "missing_due_date"
    return None


def collection_skip_reason(invoice: Invoice) -> str | None:
    if not is_commercial_sales_invoice(invoice):
        return None
    from app.services.invoice.invoice_evaluation_service import ROUTE_SALES

    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return None
    if invoice.status != InvoiceStatus.PROCESSED:
        return "not_processed"
    if not (invoice.vendor or "").strip():
        return "missing_customer"
    if invoice.total is None or invoice.total <= 0:
        return "missing_or_invalid_total"
    if invoice.due_date is None:
        return "missing_due_date"
    return None


async def _settlement_journal_exists(
    session: AsyncSession,
    *,
    payment_id: int | None = None,
    collection_id: int | None = None,
    entry_kind: JournalEntryKind,
) -> bool:
    stmt = select(func.count()).select_from(JournalEntry).where(JournalEntry.entry_kind == entry_kind)
    if payment_id is not None:
        stmt = stmt.where(JournalEntry.payment_id == payment_id)
    if collection_id is not None:
        stmt = stmt.where(JournalEntry.collection_id == collection_id)
    count = (await session.execute(stmt)).scalar() or 0
    return int(count) > 0


async def post_payment_settlement_journal(
    session: AsyncSession,
    payment: Payment,
) -> bool:
    if await _settlement_journal_exists(
        session,
        payment_id=payment.id,
        entry_kind=JournalEntryKind.PAYMENT_SETTLEMENT,
    ):
        return False

    invoice = await session.get(Invoice, payment.invoice_id)
    if invoice is None:
        await log_event(
            session,
            "settlement_journal_skipped",
            invoice_id=payment.invoice_id,
            detail={"kind": "payment", "reason": "invoice_not_found", "payment_id": payment.id},
        )
        return False

    config = await load_config_for_tenant(session, payment.tenant_id)
    bank_label = config.posting_defaults.bank_account
    if not category_resolved_in_coa(bank_label, config):
        await log_event(
            session,
            "settlement_journal_skipped",
            invoice_id=invoice.id,
            detail={
                "kind": "payment",
                "reason": "bank_account_unresolved",
                "payment_id": payment.id,
                "bank_account": bank_label,
            },
        )
        return False

    from app.services.master_data.party_coa_subledger_service import (
        resolve_settlement_control_context,
    )

    control_mapping, vendor_reg_id = await resolve_settlement_control_context(
        session,
        invoice,
        config,
        kind="vendor",
        registry_id=payment.vendor_registry_id,
    )
    if payment.vendor_registry_id is None and vendor_reg_id is not None:
        payment.vendor_registry_id = vendor_reg_id

    lines = generate_payment_settlement_entries(
        payment,
        invoice,
        config,
        control_mapping=control_mapping,
        vendor_registry_id=vendor_reg_id,
    )
    if not is_balanced(lines):
        await log_event(
            session,
            "settlement_journal_skipped",
            invoice_id=invoice.id,
            detail={"kind": "payment", "reason": "unbalanced", "payment_id": payment.id},
        )
        return False

    persist_journal_lines(
        session,
        invoice,
        lines,
        entry_kind=JournalEntryKind.PAYMENT_SETTLEMENT,
        payment_id=payment.id,
    )
    await log_event(
        session,
        "settlement_journal_posted",
        invoice_id=invoice.id,
        detail={"kind": "payment", "payment_id": payment.id, "line_count": len(lines)},
    )
    return True


async def post_collection_settlement_journal(
    session: AsyncSession,
    collection: Collection,
) -> bool:
    if await _settlement_journal_exists(
        session,
        collection_id=collection.id,
        entry_kind=JournalEntryKind.COLLECTION_SETTLEMENT,
    ):
        return False

    invoice = await session.get(Invoice, collection.invoice_id)
    if invoice is None:
        await log_event(
            session,
            "settlement_journal_skipped",
            invoice_id=collection.invoice_id,
            detail={
                "kind": "collection",
                "reason": "invoice_not_found",
                "collection_id": collection.id,
            },
        )
        return False

    config = await load_config_for_tenant(session, collection.tenant_id)
    bank_label = config.posting_defaults.bank_account
    if not category_resolved_in_coa(bank_label, config):
        await log_event(
            session,
            "settlement_journal_skipped",
            invoice_id=invoice.id,
            detail={
                "kind": "collection",
                "reason": "bank_account_unresolved",
                "collection_id": collection.id,
                "bank_account": bank_label,
            },
        )
        return False

    from app.services.master_data.party_coa_subledger_service import (
        resolve_settlement_control_context,
    )

    control_mapping, customer_reg_id = await resolve_settlement_control_context(
        session,
        invoice,
        config,
        kind="customer",
        registry_id=collection.customer_registry_id,
    )
    if collection.customer_registry_id is None and customer_reg_id is not None:
        collection.customer_registry_id = customer_reg_id

    lines = generate_collection_settlement_entries(
        collection,
        invoice,
        config,
        control_mapping=control_mapping,
        customer_registry_id=customer_reg_id,
    )
    if not is_balanced(lines):
        await log_event(
            session,
            "settlement_journal_skipped",
            invoice_id=invoice.id,
            detail={
                "kind": "collection",
                "reason": "unbalanced",
                "collection_id": collection.id,
            },
        )
        return False

    persist_journal_lines(
        session,
        invoice,
        lines,
        entry_kind=JournalEntryKind.COLLECTION_SETTLEMENT,
        collection_id=collection.id,
    )
    await log_event(
        session,
        "settlement_journal_posted",
        invoice_id=invoice.id,
        detail={
            "kind": "collection",
            "collection_id": collection.id,
            "line_count": len(lines),
        },
    )
    return True


async def ensure_payment_with_audit(
    session: AsyncSession,
    invoice: Invoice,
):
    reason = payment_skip_reason(invoice)
    payment = await ensure_payment_for_invoice(session, invoice)
    if payment is None and reason is not None:
        await log_event(
            session,
            "settlement_skipped",
            invoice_id=invoice.id,
            detail={
                "kind": "payment",
                "reason": reason,
                "route_target": invoice.route_target,
            },
        )
    return payment


async def ensure_receivable_with_audit(
    session: AsyncSession,
    invoice: Invoice,
):
    reason = collection_skip_reason(invoice)
    collection = await ensure_receivable_for_invoice(session, invoice)
    if collection is None and reason is not None:
        await log_event(
            session,
            "settlement_skipped",
            invoice_id=invoice.id,
            detail={
                "kind": "collection",
                "reason": reason,
                "route_target": invoice.route_target,
            },
        )
    return collection
