"""Reset invoice rows for reprocess / approval."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.line_item import LineItem


async def reset_invoice_for_reprocess(session: AsyncSession, inv: Invoice) -> None:
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
    inv.validation_results = None
    inv.account_code = None
    inv.account_name = None
    inv.purchase_document_type = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(JournalEntry.invoice_id == inv.id)
        )
    ).scalars().all():
        await session.delete(entry)

    for line in (
        await session.execute(select(LineItem).where(LineItem.invoice_id == inv.id))
    ).scalars().all():
        await session.delete(line)

    await session.flush()


async def clear_invoice_posting_artifacts(session: AsyncSession, inv: Invoice) -> None:
    """Remove journal/posting data when a processed invoice is rejected."""
    inv.account_code = None
    inv.account_name = None
    inv.validation_results = None

    for entry in (
        await session.execute(
            select(JournalEntry).where(JournalEntry.invoice_id == inv.id)
        )
    ).scalars().all():
        await session.delete(entry)

    for line in (
        await session.execute(select(LineItem).where(LineItem.invoice_id == inv.id))
    ).scalars().all():
        await session.delete(line)

    await session.flush()
