from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.rule_book.rule_book_mapper import ROUTE_SALES
from app.services.reconciliation.reconciliation_service import reconcile_daily


@pytest.mark.asyncio
async def test_balanced(db_session: AsyncSession) -> None:
    d = date(2026, 1, 15)
    sub, gst, total = Decimal("1000"), Decimal("100"), Decimal("1100")
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
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
    result = await reconcile_daily(db_session, d, tenant_id=TESTING_TENANT_UUID)
    assert result.is_balanced
    assert not result.halted


@pytest.mark.asyncio
async def test_halted(db_session: AsyncSession) -> None:
    d = date(2026, 1, 16)
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
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
    result = await reconcile_daily(db_session, d, tenant_id=TESTING_TENANT_UUID)
    assert result.halted
    assert not result.rc2_passed


@pytest.mark.asyncio
async def test_rc1_includes_current_invoice_before_processed(
    db_session: AsyncSession,
) -> None:
    """Invoice being reconciled counts toward RC1 even before status is processed."""
    d = date(2026, 5, 4)
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
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

    without = await reconcile_daily(db_session, d, tenant_id=TESTING_TENANT_UUID)
    assert without.total_ap_credits == Decimal("0")
    assert not without.halted

    with_current = await reconcile_daily(db_session, d, tenant_id=TESTING_TENANT_UUID, current_invoice=inv)
    assert with_current.total_ap_credits == Decimal("1100")
    assert with_current.rc1_passed
    assert with_current.is_balanced
    assert not with_current.halted


@pytest.mark.asyncio
async def test_incomplete_invoice_journal_does_not_halt_another_invoice(
    db_session: AsyncSession,
) -> None:
    """Accruals left behind by a halted invoice must not fail RC1 for its date."""
    d = date(2026, 5, 5)
    stranded = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Lexar Co",
        invoice_no="STRANDED-1",
        invoice_date=d,
        subtotal=Decimal("18864"),
        total=Decimal("18864"),
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="rc1-stranded",
    )
    current = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Betacarbon",
        invoice_no="CURRENT-1",
        invoice_date=d,
        subtotal=Decimal("70000"),
        total=Decimal("70000"),
        status=InvoiceStatus.RECONCILING,
        currency="AUD",
        file_hash="rc1-current-ok",
    )
    db_session.add_all([stranded, current])
    await db_session.flush()

    for inv in (stranded, current):
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
                )
            )
    await db_session.flush()

    result = await reconcile_daily(
        db_session, d, tenant_id=TESTING_TENANT_UUID, current_invoice=current
    )
    assert result.purchase_invoice_total == Decimal("70000")
    assert result.total_ap_credits == Decimal("70000")
    assert result.rc1_passed
    assert not result.halted


@pytest.mark.asyncio
async def test_unbalanced_journal_on_current_invoice_still_halts(
    db_session: AsyncSession,
) -> None:
    """Filtering by countable invoices must not hide a bad write on the current invoice."""
    d = date(2026, 5, 6)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="CURRENT-BAD",
        invoice_date=d,
        subtotal=Decimal("500"),
        total=Decimal("500"),
        status=InvoiceStatus.RECONCILING,
        currency="AUD",
        file_hash="rc1-current-bad",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6100", "Operating Expenses", Decimal("500"), Decimal("0"), EntryType.DEBIT),
        ("2000", "Accounts Payable", Decimal("0"), Decimal("400"), EntryType.CREDIT),
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

    result = await reconcile_daily(
        db_session, d, tenant_id=TESTING_TENANT_UUID, current_invoice=inv
    )
    assert result.halted
    assert not result.rc1_passed


@pytest.mark.asyncio
async def test_reconciliation_scoped_per_org(db_session: AsyncSession) -> None:
    """Journal entries from another org must not affect RC1/RC2."""
    d = date(2026, 5, 4)
    org2 = Invoice(
        tenant_id=PLATFORM_TENANT_UUID,
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
        tenant_id=TESTING_TENANT_UUID,
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

    result = await reconcile_daily(db_session, d, tenant_id=PLATFORM_TENANT_UUID, current_invoice=org2)
    assert result.rc1_passed
    assert result.is_balanced
    assert not result.halted


@pytest.mark.asyncio
async def test_rc1_excludes_undated_current_invoice_from_totals(
    db_session: AsyncSession,
) -> None:
    """Undated invoices must not accrue — invoice side stays 0 even if journals exist."""
    d = date.today()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="MongoDB",
        invoice_no="UNDATED-663",
        invoice_date=None,
        subtotal=Decimal("33.70"),
        gst=Decimal("3.38"),
        total=Decimal("37.08"),
        status=InvoiceStatus.RECONCILING,
        currency="USD",
        file_hash="rc1-undated",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6100", "Operating Expenses", Decimal("33.70"), Decimal("0"), EntryType.DEBIT),
        ("1400", "GST Paid", Decimal("3.38"), Decimal("0"), EntryType.DEBIT),
        ("2000", "Accounts Payable", Decimal("0"), Decimal("37.08"), EntryType.CREDIT),
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

    result = await reconcile_daily(
        db_session, d, tenant_id=TESTING_TENANT_UUID, current_invoice=inv
    )
    assert result.purchase_invoice_total == Decimal("0")
    assert result.total_ap_credits == Decimal("37.08")
    assert result.halted
    assert not result.rc1_passed


@pytest.mark.asyncio
async def test_rc1_uses_rule_book_payable_code(db_session: AsyncSession) -> None:
    d = date(2026, 6, 1)
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(payable_account="Trade Creditors"),
        chart_of_accounts=[
            ChartOfAccountEntry(code="2100", name="Trade Creditors", type="Liability"),
            ChartOfAccountEntry(code="6100", name="Expenses", type="Expense"),
            ChartOfAccountEntry(code="1400", name="GST Paid", type="Asset"),
        ],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-2100",
        invoice_date=d,
        subtotal=Decimal("300"),
        gst=Decimal("30"),
        total=Decimal("330"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="rc1-2100",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6100", "Expenses", Decimal("300"), Decimal("0"), EntryType.DEBIT),
        ("1400", "GST Paid", Decimal("30"), Decimal("0"), EntryType.DEBIT),
        ("2100", "Trade Creditors", Decimal("0"), Decimal("330"), EntryType.CREDIT),
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

    result = await reconcile_daily(
        db_session, d, tenant_id=TESTING_TENANT_UUID, config=config
    )
    assert result.rc1_passed
    assert not result.halted


@pytest.mark.asyncio
async def test_rc1_sales_route_matches_receivable_debits(db_session: AsyncSession) -> None:
    d = date(2026, 6, 2)
    config = RuleBookConfigPayload(
        chart_of_accounts=[
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="4100", name="Sales Revenue", type="Revenue"),
            ChartOfAccountEntry(code="2300", name="GST Collected", type="Liability"),
        ],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-SALES",
        invoice_date=d,
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.RECONCILING,
        currency="AUD",
        file_hash="rc1-sales",
        route_target=ROUTE_SALES,
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("1200", "Accounts Receivable", Decimal("1100"), Decimal("0"), EntryType.DEBIT),
        ("4100", "Sales Revenue", Decimal("0"), Decimal("1000"), EntryType.CREDIT),
        ("2300", "GST Collected", Decimal("0"), Decimal("100"), EntryType.CREDIT),
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

    result = await reconcile_daily(
        db_session,
        d,
        tenant_id=TESTING_TENANT_UUID,
        current_invoice=inv,
        config=config,
    )
    assert result.rc1_passed
    assert result.is_balanced
    assert not result.halted


@pytest.mark.asyncio
async def test_rc1_ignores_processed_supporting_po_totals(
    db_session: AsyncSession,
) -> None:
    """Processed PO totals must not poison purchase RC1 for a sales invoice same day."""
    d = date(2026, 6, 15)
    config = RuleBookConfigPayload(
        chart_of_accounts=[
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="4100", name="Sales Revenue", type="Revenue"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )
    po = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no=None,
        invoice_date=d,
        total=Decimal("5500"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="rc1-po-support",
        route_target="Purchase Management",
        purchase_document_type="po",
        document_type_code="DT-02",
        document_heading="PURCHASE ORDER",
        evaluation_status="auto_coded",
    )
    sales = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-SAL-001",
        invoice_date=d,
        subtotal=Decimal("900"),
        gst=Decimal("90"),
        total=Decimal("990"),
        status=InvoiceStatus.RECONCILING,
        currency="AUD",
        file_hash="rc1-sales-vs-po",
        route_target=ROUTE_SALES,
        sales_document_type="invoice",
        document_type_code="DT-07",
    )
    db_session.add_all([po, sales])
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("1200", "Accounts Receivable", Decimal("990"), Decimal("0"), EntryType.DEBIT),
        ("4100", "Sales Revenue", Decimal("0"), Decimal("990"), EntryType.CREDIT),
    ]:
        db_session.add(
            JournalEntry(
                invoice_id=sales.id,
                date=d,
                account_code=code,
                account_name=name,
                debit=dr,
                credit=cr,
                entry_type=et,
            )
        )
    await db_session.flush()

    result = await reconcile_daily(
        db_session,
        d,
        tenant_id=TESTING_TENANT_UUID,
        current_invoice=sales,
        config=config,
    )
    assert result.purchase_invoice_total == Decimal("0")
    assert result.sales_invoice_total == Decimal("990")
    assert result.rc1_passed
    assert not result.halted
