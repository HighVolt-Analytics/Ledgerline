from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.services.reconciliation_service import reconcile_daily


@pytest.mark.asyncio
async def test_balanced(db_session: AsyncSession) -> None:
    d = date(2026, 1, 15)
    sub, gst, total = Decimal("1000"), Decimal("100"), Decimal("1100")
    inv = Invoice(org_id=1,
        vendor="Acme",
        invoice_no="INV-R1",
        invoice_date=d,
        subtotal=sub,
        gst=gst,
        total=total,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="r1",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6100", "Exp", sub, Decimal("0"), EntryType.DEBIT),
        ("1400", "GST", gst, Decimal("0"), EntryType.DEBIT),
        ("2000", "AP", Decimal("0"), total, EntryType.CREDIT),
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
            )
        )
    await db_session.flush()
    result = await reconcile_daily(db_session, d, org_id=1)
    assert result.is_balanced
    assert not result.halted


@pytest.mark.asyncio
async def test_halted(db_session: AsyncSession) -> None:
    d = date(2026, 1, 16)
    inv = Invoice(org_id=1,
        invoice_no="INV-R2",
        invoice_date=d,
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="r2",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=d,
            account_code="6100",
            account_name="Exp",
            debit=Decimal("100"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=d,
            account_code="2000",
            account_name="AP",
            debit=Decimal("0"),
            credit=Decimal("50"),
            entry_type=EntryType.CREDIT,
        )
    )
    await db_session.flush()
    result = await reconcile_daily(db_session, d, org_id=1)
    assert result.halted
    assert not result.rc2_passed


@pytest.mark.asyncio
async def test_rc1_includes_current_invoice_before_processed(
    db_session: AsyncSession,
) -> None:
    """Invoice being reconciled counts toward RC1 even before status is processed."""
    d = date(2026, 5, 4)
    inv = Invoice(org_id=1,
        vendor="Atlassian Pty Ltd",
        invoice_no="ATL-TEST",
        invoice_date=d,
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.RECONCILING,
        currency="AUD",
        file_hash="rc1_current",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6120", "Software Subscription Expense", Decimal("1000"), Decimal("0"), EntryType.DEBIT),
        ("1400", "GST Paid", Decimal("100"), Decimal("0"), EntryType.DEBIT),
        ("2000", "Accounts Payable", Decimal("0"), Decimal("1100"), EntryType.CREDIT),
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
            )
        )
    await db_session.flush()

    without = await reconcile_daily(db_session, d, org_id=1)
    assert without.halted

    with_current = await reconcile_daily(db_session, d, org_id=1, current_invoice=inv)
    assert with_current.rc1_passed
    assert with_current.is_balanced
    assert not with_current.halted


@pytest.mark.asyncio
async def test_reconciliation_scoped_per_org(db_session: AsyncSession) -> None:
    """Journal entries from another org must not affect RC1/RC2."""
    d = date(2026, 5, 4)
    org2 = Invoice(
        org_id=2,
        vendor="Atlassian Pty Ltd",
        invoice_no="ATL-ORG2",
        invoice_date=d,
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.RECONCILING,
        currency="AUD",
        file_hash="org2-rc",
    )
    org1 = Invoice(
        org_id=1,
        vendor="Atlassian Pty Ltd",
        invoice_no="ATL-ORG1",
        invoice_date=d,
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="org1-rc",
    )
    db_session.add_all([org2, org1])
    await db_session.flush()

    for inv in (org1, org2):
        for code, name, dr, cr, et in [
            ("6120", "Software", Decimal("1000"), Decimal("0"), EntryType.DEBIT),
            ("1400", "GST", Decimal("100"), Decimal("0"), EntryType.DEBIT),
            ("2000", "AP", Decimal("0"), Decimal("1100"), EntryType.CREDIT),
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
                )
            )
    await db_session.flush()

    result = await reconcile_daily(db_session, d, org_id=2, current_invoice=org2)
    assert result.rc1_passed
    assert result.is_balanced
    assert not result.halted
