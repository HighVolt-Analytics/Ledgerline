"""Reconciliation overview mixed-currency aggregation."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.services.reconciliation.reconciliation_overview import build_reconciliation_overview
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_overview_mixed_currency_not_summed_as_base(db_session: AsyncSession) -> None:
    inv_date = date(2026, 5, 2)
    aud = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="BrightDesk Supplies Pty Ltd",
        document_ref="DOC-7",
        invoice_date=inv_date,
        subtotal=Decimal("271.82"),
        gst=Decimal("27.18"),
        total=Decimal("299.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash="mix_aud",
    )
    inr = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="MAKEMYTRIP (INDIA)",
        document_ref="DOC-85",
        invoice_date=inv_date,
        subtotal=Decimal("9744.61"),
        gst=Decimal("55.92"),
        total=Decimal("9800.53"),
        currency="INR",
        status=InvoiceStatus.PROCESSED,
        file_hash="mix_inr",
    )
    db_session.add_all([aud, inr])
    await db_session.flush()

    for inv, postings in [
        (
            aud,
            [
                ("6100", "Operating Expenses", Decimal("271.82"), Decimal("0")),
                ("1400", "GST Paid", Decimal("27.18"), Decimal("0")),
                ("2000", "Accounts Payable", Decimal("0"), Decimal("299.00")),
            ],
        ),
        (
            inr,
            [
                ("6100", "Operating Expenses", Decimal("9744.61"), Decimal("0")),
                ("1400", "GST Paid", Decimal("55.92"), Decimal("0")),
                ("2000", "Accounts Payable", Decimal("0"), Decimal("9800.53")),
            ],
        ),
    ]:
        for code, name, dr, cr in postings:
            db_session.add(
                JournalEntry(
                    tenant_id=TESTING_TENANT_UUID,
                    invoice_id=inv.id,
                    date=inv_date,
                    account_code=code,
                    account_name=name,
                    debit=dr,
                    credit=cr,
                    entry_type=EntryType.DEBIT if dr > 0 else EntryType.CREDIT,
                )
            )
    await db_session.flush()

    overview = await build_reconciliation_overview(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
    )

    assert overview.has_mixed_currencies is True
    # Base totals must only include AUD documents — not INR amounts relabelled as AUD.
    assert overview.sum_totals == Decimal("299.00")
    assert overview.sum_dr == Decimal("299.00")
    assert overview.sum_cr == Decimal("299.00")
    assert overview.totals_by_currency["AUD"] == Decimal("299.00")
    assert overview.totals_by_currency["INR"] == Decimal("9800.53")
    assert overview.dr_by_currency["INR"] == Decimal("9800.53")
    assert overview.balanced is True

    day = overview.by_date[0]
    assert day.has_mixed_currencies is True
    assert day.sum_dr == Decimal("0.00")
    assert day.sum_cr == Decimal("0.00")
    assert day.invoices[0].currency in {"AUD", "INR"}
    assert {row.currency for row in day.invoices} == {"AUD", "INR"}
