"""Helpers for seeding journal_entries under a JournalBatch (required post-099)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.journal import EntryType, JournalEntry, JournalEntryKind
from app.models.journal_batch import JournalBatch, JournalBatchStatus


async def seed_journal_batch(
    session: AsyncSession,
    invoice: Invoice,
    lines: list[tuple[str, str, Decimal, Decimal, EntryType]],
    *,
    entry_kind: JournalEntryKind = JournalEntryKind.INVOICE_ACCRUAL,
    payment_id: int | None = None,
    collection_id: int | None = None,
    entry_date: date | None = None,
    vendor_registry_id: int | None = None,
    customer_registry_id: int | None = None,
) -> JournalBatch:
    """Insert one POSTED batch and attach every line via ``entry.batch = batch``."""
    batch = JournalBatch(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        entry_kind=entry_kind,
        payment_id=payment_id,
        collection_id=collection_id,
        status=JournalBatchStatus.POSTED.value,
    )
    session.add(batch)
    on = entry_date or invoice.invoice_date or date.today()
    for code, name, debit, credit, entry_type in lines:
        session.add(
            JournalEntry(
                batch=batch,
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                date=on,
                account_code=code,
                account_name=name,
                debit=debit,
                credit=credit,
                entry_type=entry_type,
                entry_kind=entry_kind,
                payment_id=payment_id,
                collection_id=collection_id,
                vendor_registry_id=vendor_registry_id,
                customer_registry_id=customer_registry_id,
            )
        )
    await session.flush()
    return batch
