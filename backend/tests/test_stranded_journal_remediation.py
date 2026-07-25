"""RC1 stranded-journal remediation and status policy."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry, JournalEntryKind
from app.services.reconciliation.reconciliation_service import (
    RC1_COUNTABLE_STATUSES,
    RC1_EXCLUDED_STATUSES,
)
from app.services.reconciliation.stranded_journal_remediation import (
    RC1_STRANDED_INVOICE_STATUSES,
    purge_stranded_accrual_journals,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_rc1_status_policy_partitions_all_invoice_statuses() -> None:
    all_statuses = set(InvoiceStatus)
    assert RC1_COUNTABLE_STATUSES.isdisjoint(RC1_EXCLUDED_STATUSES)
    assert RC1_COUNTABLE_STATUSES | RC1_EXCLUDED_STATUSES == all_statuses
    assert RC1_COUNTABLE_STATUSES == frozenset({InvoiceStatus.PROCESSED})
    assert RC1_STRANDED_INVOICE_STATUSES <= RC1_EXCLUDED_STATUSES


@pytest.mark.asyncio
async def test_purge_stranded_accruals_removes_exception_keeps_processed(
    db_session: AsyncSession,
) -> None:
    d = date(2026, 7, 25)
    stranded = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Lexar Co",
        invoice_no="82507681",
        invoice_date=d,
        subtotal=Decimal("18864"),
        total=Decimal("18864"),
        status=InvoiceStatus.EXCEPTION,
        currency="USD",
        file_hash="purge-stranded",
        evaluation_status="awaiting_po",
    )
    completed = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Betacarbon",
        invoice_no="AD3703250209146",
        invoice_date=d,
        subtotal=Decimal("70000"),
        total=Decimal("70000"),
        status=InvoiceStatus.PROCESSED,
        currency="USD",
        file_hash="purge-ok",
    )
    db_session.add_all([stranded, completed])
    await db_session.flush()

    for inv in (stranded, completed):
        for code, name, dr, cr, et in [
            ("6100", "Operating Expenses", inv.total, Decimal("0"), EntryType.DEBIT),
            ("2000", "Accounts Payable", Decimal("0"), inv.total, EntryType.CREDIT),
        ]:
            db_session.add(
                JournalEntry(
                    invoice_id=inv.id,
                    date=d,
                    account_code=code,
                    account_name=name,
                    debit=dr,
                    credit=cr,
                    entry_type=et,
                    entry_kind=JournalEntryKind.INVOICE_ACCRUAL,
                )
            )
    await db_session.flush()

    result = await purge_stranded_accrual_journals(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        recon_date=d,
        reason="test_backfill",
    )
    assert result.invoice_ids == [stranded.id]
    assert result.entries_deleted == 2

    stranded_left = (
        await db_session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.invoice_id == stranded.id)
        )
    ).scalar_one()
    completed_left = (
        await db_session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.invoice_id == completed.id)
        )
    ).scalar_one()
    assert stranded_left == 0
    assert completed_left == 2


@pytest.mark.asyncio
async def test_purge_does_not_remove_payment_settlement_rows(
    db_session: AsyncSession,
) -> None:
    d = date(2026, 7, 26)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="SETTLE-1",
        invoice_date=d,
        total=Decimal("100"),
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="purge-settle",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=d,
            account_code="2000",
            account_name="AP",
            debit=Decimal("0"),
            credit=Decimal("100"),
            entry_type=EntryType.CREDIT,
            entry_kind=JournalEntryKind.INVOICE_ACCRUAL,
        )
    )
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=d,
            account_code="2000",
            account_name="AP",
            debit=Decimal("100"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
            entry_kind=JournalEntryKind.PAYMENT_SETTLEMENT,
        )
    )
    await db_session.flush()

    result = await purge_stranded_accrual_journals(
        db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
    )
    assert result.entries_deleted == 1
    kinds = (
        await db_session.execute(
            select(JournalEntry.entry_kind).where(JournalEntry.invoice_id == inv.id)
        )
    ).scalars().all()
    assert kinds == [JournalEntryKind.PAYMENT_SETTLEMENT]
