"""Reset invoice rows for reprocess / approval."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.services.processing_override_catalog import skip_steps_for
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice


async def reset_invoice_for_reprocess(
    session: AsyncSession,
    inv: Invoice,
    *,
    preserve_document_type: bool = False,
) -> None:
    """Clear extracted data and journal lines; set status to pending."""
    inv.status = InvoiceStatus.PENDING
    inv.vendor = None
    inv.abn = None
    inv.invoice_no = None
    inv.po_reference = None
    inv.cost_centre = None
    inv.invoice_date = None
    inv.due_date = None
    inv.subtotal = None
    inv.gst = None
    inv.total = None
    inv.billing_address = None
    inv.bank_bsb = None
    inv.bank_account = None
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None
    inv.purchase_document_type = None
    if not preserve_document_type:
        inv.document_type_code = None
        inv.document_type_confidence = None
        inv.llm_suggested_dt = None
        inv.llm_confidence = None
    inv.document_text = None
    inv.document_heading = None
    inv.extracted_fields = None
    inv.route_target = None
    inv.matched_rule_ids = None
    inv.evaluation_status = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all():
        await session.delete(entry)

    for line in (
        await session.execute(select(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id)))
    ).scalars().all():
        await session.delete(line)

    await session.flush()


async def reset_invoice_for_approval(session: AsyncSession, inv: Invoice) -> None:
    """Re-queue for pipeline while preserving user-corrected extracted fields."""
    inv.status = InvoiceStatus.PENDING
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all():
        await session.delete(entry)

    await session.flush()


async def clear_invoice_posting_artifacts(session: AsyncSession, inv: Invoice) -> None:
    """Remove journal/posting data when a processed invoice is rejected."""
    inv.account_code = None
    inv.account_name = None
    inv.validation_results = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalars().all():
        await session.delete(entry)

    for line in (
        await session.execute(select(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id)))
    ).scalars().all():
        await session.delete(line)

    await session.flush()


async def should_preserve_extracted_on_requeue(
    session: AsyncSession,
    inv: Invoice,
    *,
    manual_edits: bool | None = None,
) -> bool:
    """Keep clerk-corrected header fields when re-queuing from the review queue."""
    if inv.status != InvoiceStatus.EXCEPTION:
        return False
    from app.services.approval_pipeline_service import payable_fields_complete
    from app.services.invoice_edit_service import invoice_has_manual_field_edits

    if manual_edits is None:
        manual_edits = await invoice_has_manual_field_edits(
            session,
            inv.id,
            tenant_id=inv.tenant_id,
        )
    return manual_edits or payable_fields_complete(inv)


async def requeue_invoice_for_pipeline(
    session: AsyncSession,
    inv: Invoice,
    *,
    preserve_document_type: bool = False,
    preserve_extracted_fields: bool = False,
) -> None:
    """Reset posting artifacts; optionally wipe or keep extracted header fields."""
    if preserve_extracted_fields:
        await reset_invoice_for_approval(session, inv)
        return
    keep_dt = preserve_document_type or "classification" in skip_steps_for(inv)
    await reset_invoice_for_reprocess(session, inv, preserve_document_type=keep_dt)
