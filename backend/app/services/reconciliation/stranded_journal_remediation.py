"""Remediate accrual journals left behind by incomplete invoices.

RC1 only counts PROCESSED invoices (plus the invoice currently being
reconciled). Accrual rows for incomplete invoices must be removed so they
cannot drift the day-level ledger forever — even though RC1 already ignores
them after the countable-status filter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry, JournalEntryKind
from app.services.audit.audit_service import log_event
from app.tenant_child_tables import journal_entries_for_invoice
from app.services.payments.journal_reversal_service import reverse_batches_for_entries

# Terminal / blocked statuses whose invoice totals do NOT enter RC1.
# Accrual journals for these invoices are safe to purge.
RC1_STRANDED_INVOICE_STATUSES: frozenset[InvoiceStatus] = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)


@dataclass(frozen=True)
class StrandedJournalPurgeResult:
    invoice_ids: list[int]
    entries_deleted: int


async def purge_accrual_journals_for_invoice(
    session: AsyncSession,
    invoice: Invoice,
    *,
    reason: str,
    audit: bool = True,
) -> int:
    """Reverse INVOICE_ACCRUAL rows for one invoice (settlements kept)."""
    entries = (
        await session.execute(
            select(JournalEntry).where(
                *journal_entries_for_invoice(invoice.tenant_id, invoice.id),
                JournalEntry.entry_kind == JournalEntryKind.INVOICE_ACCRUAL,
            )
        )
    ).scalars().all()
    if not entries:
        return 0
    await reverse_batches_for_entries(session, entries, reason=reason)
    if audit:
        await log_event(
            session,
            "stranded_accrual_journals_purged",
            invoice_id=invoice.id,
            tenant_id=invoice.tenant_id,
            detail={
                "reason": reason,
                "entries_deleted": len(entries),
                "invoice_status": getattr(invoice.status, "value", str(invoice.status)),
                "evaluation_status": invoice.evaluation_status,
            },
        )
    return len(entries)


async def purge_stranded_accrual_journals(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | int,
    recon_date: date | None = None,
    invoice_id: int | None = None,
    reason: str = "remediation_backfill",
) -> StrandedJournalPurgeResult:
    """Purge accrual journals for incomplete invoices in a tenant (or one day).

    Targets invoices whose status is in ``RC1_STRANDED_INVOICE_STATUSES`` and
    that still have ``INVOICE_ACCRUAL`` journal rows. Optional filters:
    ``recon_date`` (invoice_date / journal date) and ``invoice_id``.
    """
    inv_filters = [
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(tuple(RC1_STRANDED_INVOICE_STATUSES)),
    ]
    if invoice_id is not None:
        inv_filters.append(Invoice.id == invoice_id)
    if recon_date is not None:
        inv_filters.append(Invoice.invoice_date == recon_date)

    invoices = (
        await session.execute(select(Invoice).where(*inv_filters).order_by(Invoice.id))
    ).scalars().all()

    touched: list[int] = []
    deleted = 0
    for inv in invoices:
        entry_filters = [
            *journal_entries_for_invoice(inv.tenant_id, inv.id),
            JournalEntry.entry_kind == JournalEntryKind.INVOICE_ACCRUAL,
        ]
        if recon_date is not None:
            entry_filters.append(JournalEntry.date == recon_date)
        entries = (
            await session.execute(select(JournalEntry).where(*entry_filters))
        ).scalars().all()
        if not entries:
            continue
        await reverse_batches_for_entries(session, entries, reason=reason)
        deleted += len(entries)
        touched.append(inv.id)
        await log_event(
            session,
            "stranded_accrual_journals_purged",
            invoice_id=inv.id,
            tenant_id=inv.tenant_id,
            detail={
                "reason": reason,
                "entries_deleted": len(entries),
                "invoice_status": getattr(inv.status, "value", str(inv.status)),
                "evaluation_status": inv.evaluation_status,
                "recon_date": recon_date.isoformat() if recon_date else None,
            },
        )

    await session.flush()
    return StrandedJournalPurgeResult(invoice_ids=touched, entries_deleted=deleted)
