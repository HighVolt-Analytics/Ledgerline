"""Accrual date policy tests."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.services.invoice.invoice_accrual_date import halt_if_missing_accrual_date
from app.services.payments.journal_generator import generate_entries
from app.services.rule_book.account_mapper import AccountMapping
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_halt_if_missing_accrual_date_blocks_undated_invoice(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="MongoDB",
        invoice_no="NO-DATE",
        invoice_date=None,
        total=Decimal("37.08"),
        status=InvoiceStatus.MAPPING,
        currency="USD",
        file_hash="accrual-date-missing",
    )
    db_session.add(inv)
    await db_session.flush()

    halted = await halt_if_missing_accrual_date(db_session, inv)
    assert halted is True
    assert inv.status == InvoiceStatus.EXCEPTION
    assert inv.evaluation_status == "needs_review"


def test_generate_entries_requires_invoice_date() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="MongoDB",
        invoice_no="NO-DATE",
        invoice_date=None,
        subtotal=Decimal("33.70"),
        gst=Decimal("3.38"),
        total=Decimal("37.08"),
        status=InvoiceStatus.JOURNALING,
        currency="USD",
        file_hash="journal-no-date",
    )
    mapping = AccountMapping(account_code="6100", account_name="Operating Expenses")
    assert generate_entries(inv, mapping) == []


def test_generate_entries_uses_invoice_date_not_today() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="MongoDB",
        invoice_no="DATED",
        invoice_date=date(2025, 7, 7),
        subtotal=Decimal("33.70"),
        gst=Decimal("3.38"),
        total=Decimal("37.08"),
        status=InvoiceStatus.JOURNALING,
        currency="USD",
        file_hash="journal-dated",
    )
    mapping = AccountMapping(account_code="6100", account_name="Operating Expenses")
    lines = generate_entries(inv, mapping)
    assert lines
    assert all(line.date == date(2025, 7, 7) for line in lines)
