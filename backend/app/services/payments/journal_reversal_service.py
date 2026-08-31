"""Reverse a posted journal batch instead of deleting/rewriting its rows.

journal_entries is append-only (see migration 100's immutability trigger):
nothing may UPDATE or DELETE a posted row. Every correction — remap,
invoice reset, stranded-journal cleanup — goes through reverse_batch()
instead, which posts a new balanced batch with debit/credit swapped and
marks the original batch REVERSED. History is preserved end to end.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.journal import EntryType, JournalEntry
from app.models.journal_batch import JournalBatch, JournalBatchStatus
from app.services.payments.fiscal_period_service import ensure_period_open


async def reverse_batch(
    session: AsyncSession,
    batch: JournalBatch,
    *,
    reason: str,
) -> JournalBatch | None:
    """Post a reversing batch for `batch` and mark it REVERSED.

    Returns the new reversal JournalBatch, or None if `batch` was already
    reversed, is itself a reversing batch, or has no entries (nothing to do).

    Reversal batches (those with ``reversal_reason`` set) must not be reversed
    again: a remap/reset that selects all accrual lines would otherwise reverse
    the reversing batch and restore the original posting, double-counting when
    a replacement accrual is also posted.
    """
    if (batch.reversal_reason or "").strip():
        return None

    # Claim the original batch in one conditional UPDATE so two concurrent
    # reverse_batch() calls cannot both post a reversing journal.
    claim = await session.execute(
        update(JournalBatch)
        .where(
            JournalBatch.id == batch.id,
            JournalBatch.status == JournalBatchStatus.POSTED.value,
            JournalBatch.reversed_by_batch_id.is_(None),
            or_(
                JournalBatch.reversal_reason.is_(None),
                JournalBatch.reversal_reason == "",
            ),
        )
        .values(status=JournalBatchStatus.REVERSED.value)
        .execution_options(synchronize_session="fetch")
    )
    if claim.rowcount != 1:
        return None

    entries = (
        await session.execute(
            select(JournalEntry).where(JournalEntry.batch_id == batch.id)
        )
    ).scalars().all()
    if not entries:
        batch.status = JournalBatchStatus.POSTED.value
        await session.flush()
        return None

    reversal = JournalBatch(
        tenant_id=batch.tenant_id,
        invoice_id=batch.invoice_id,
        entry_kind=batch.entry_kind,
        payment_id=batch.payment_id,
        collection_id=batch.collection_id,
        status=JournalBatchStatus.POSTED.value,
        reversal_reason=reason,
    )
    session.add(reversal)

    # Reversal lands today, not on the original entry date — an old fiscal
    # period should not be silently reopened by a correction.
    today = date.today()
    await ensure_period_open(session, batch.tenant_id, today)
    for entry in entries:
        swapped_type = (
            EntryType.CREDIT if entry.entry_type == EntryType.DEBIT else EntryType.DEBIT
        )
        session.add(
            JournalEntry(
                batch=reversal,
                tenant_id=entry.tenant_id,
                invoice_id=entry.invoice_id,
                date=today,
                account_code=entry.account_code,
                account_name=entry.account_name,
                debit=entry.credit,
                credit=entry.debit,
                entry_type=swapped_type,
                vendor_registry_id=entry.vendor_registry_id,
                customer_registry_id=entry.customer_registry_id,
                entry_kind=entry.entry_kind,
                payment_id=entry.payment_id,
                collection_id=entry.collection_id,
                txn_currency=entry.txn_currency,
                base_currency=entry.base_currency,
                base_debit=entry.base_credit,
                base_credit=entry.base_debit,
                fx_rate=entry.fx_rate,
                fx_source=entry.fx_source,
            )
        )

    # Flush the reversal + its entries first so reversal.id exists before we
    # point the original batch at it.
    await session.flush()
    batch.reversed_by_batch_id = reversal.id
    await session.flush()
    return reversal


async def reverse_batches_for_entries(
    session: AsyncSession,
    entries: list[JournalEntry],
    *,
    reason: str,
) -> list[JournalBatch]:
    """Reverse every distinct batch referenced by `entries`.

    Convenience for callers that already loaded a set of JournalEntry rows
    (by invoice, by entry_kind, ...) and previously deleted them outright.
    """
    batch_ids = {entry.batch_id for entry in entries if entry.batch_id is not None}
    reversed_batches: list[JournalBatch] = []
    for batch_id in batch_ids:
        batch = await session.get(JournalBatch, batch_id)
        if batch is None:
            continue
        result = await reverse_batch(session, batch, reason=reason)
        if result is not None:
            reversed_batches.append(result)
    return reversed_batches
