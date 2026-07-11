"""Persist journal lines to the database."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.journal import JournalEntry, JournalEntryKind
from app.services.payments.journal_generator import JournalLine


def persist_journal_lines(
    session: AsyncSession,
    invoice: Invoice,
    lines: list[JournalLine],
    *,
    entry_kind: JournalEntryKind = JournalEntryKind.INVOICE_ACCRUAL,
    payment_id: int | None = None,
    collection_id: int | None = None,
) -> None:
    for line in lines:
        session.add(
            JournalEntry(
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                date=line.date,
                account_code=line.account_code,
                account_name=line.account_name,
                debit=line.debit,
                credit=line.credit,
                entry_type=line.entry_type,
                vendor_registry_id=line.vendor_registry_id,
                customer_registry_id=line.customer_registry_id,
                entry_kind=entry_kind,
                payment_id=payment_id,
                collection_id=collection_id,
            )
        )
