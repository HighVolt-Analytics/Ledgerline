from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType
from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults, RuleBookConfigPayload
from app.services.rule_book.account_mapper import AccountMapping
from app.services.rule_book.rule_book_mapper import ROUTE_SALES
from app.services.payments.journal_generator import generate_entries, is_balanced


def test_balanced() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 1, 15),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    lines = generate_entries(inv, AccountMapping("6100", "Software"))
    assert len(lines) == 3
    assert is_balanced(lines)


def test_ap_credit() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 1, 15),
        subtotal=Decimal("500"),
        gst=Decimal("50"),
        total=Decimal("550"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    ap = [ln for ln in generate_entries(inv, AccountMapping("6200", "Supplies")) if ln.credit > 0]
    assert ap[0].credit == Decimal("550")


def test_total_only_infers_subtotal_for_ap() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        subtotal=None,
        gst=None,
        total=Decimal("2580"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    lines = generate_entries(inv, AccountMapping("6130", "Marketing Expense"))
    assert is_balanced(lines)
    expense = [ln for ln in lines if ln.debit > 0 and ln.entry_type == EntryType.DEBIT]
    assert expense[0].debit == Decimal("2580")


def test_total_only_infers_subtotal_for_sales() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 3, 1),
        subtotal=None,
        gst=None,
        total=Decimal("2580"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        route_target=ROUTE_SALES,
    )
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="4100", name="Sales Revenue", type="Revenue"),
            ChartOfAccountEntry(code="2300", name="GST Collected", type="Liability"),
        ],
    )
    lines = generate_entries(
        inv,
        AccountMapping("4100", "Sales Revenue"),
        config=config,
    )
    assert is_balanced(lines)


def test_sales_route_journal() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 2, 1),
        subtotal=Decimal("2000"),
        gst=Decimal("200"),
        total=Decimal("2200"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        route_target=ROUTE_SALES,
    )
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1200", name="Accounts Receivable", type="Asset"),
            ChartOfAccountEntry(code="4100", name="Sales Revenue", type="Revenue"),
            ChartOfAccountEntry(code="2300", name="GST Collected", type="Liability"),
        ],
    )
    lines = generate_entries(
        inv,
        AccountMapping("4100", "Sales Revenue"),
        config=config,
    )
    assert len(lines) == 3
    assert is_balanced(lines)
    receivable = [ln for ln in lines if ln.debit > 0]
    assert receivable[0].account_code == "1200"
    assert receivable[0].debit == Decimal("2200")
