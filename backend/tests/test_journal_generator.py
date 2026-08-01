from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType
from app.models.line_item import LineItem
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


def test_line_items_infer_subtotal_and_total_for_ap() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 6, 24),
        subtotal=None,
        gst=Decimal("50"),
        total=None,
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
    )
    inv.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="Fresh Produce Mixed Box",
            qty=Decimal("10"),
            amount=Decimal("500"),
        )
    ]
    lines = generate_entries(inv, AccountMapping("6130", "Marketing Expense"))
    assert is_balanced(lines)
    payable = [ln for ln in lines if ln.credit > 0]
    assert payable[0].credit == Decimal("550")
    expense = [ln for ln in lines if ln.account_code == "6130"]
    assert expense[0].debit == Decimal("500")


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


def test_purchase_journal_splits_by_line_sub_ledger() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 4, 1),
        subtotal=Decimal("300"),
        gst=Decimal("30"),
        total=Decimal("330"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        account_name="Cloud Hosting Expense",
    )
    inv.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="AWS",
            amount=Decimal("200"),
            sub_ledger="AWS Production",
        ),
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="Azure",
            amount=Decimal("100"),
            sub_ledger="Azure Staging",
        ),
    ]
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(
                code="6110",
                name="Cloud Hosting Expense",
                type="Expense",
                sub_ledgers=[
                    {"code": "01", "name": "AWS Production"},
                    {"code": "02", "name": "Azure Staging"},
                ],
            ),
            ChartOfAccountEntry(code="1400", name="Tax Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )
    lines = generate_entries(
        inv,
        AccountMapping("6110", "Cloud Hosting Expense"),
        config=config,
    )
    assert is_balanced(lines)
    expense = [ln for ln in lines if ln.debit > 0 and ln.account_code.startswith("6110")]
    assert {ln.account_code: ln.debit for ln in expense} == {
        "6110-01": Decimal("200"),
        "6110-02": Decimal("100"),
    }


def test_purchase_journal_residual_goes_to_parent() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 4, 2),
        subtotal=Decimal("250"),
        gst=Decimal("25"),
        total=Decimal("275"),
        status=InvoiceStatus.JOURNALING,
        currency="AUD",
        account_name="Cloud Hosting Expense",
    )
    inv.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="AWS",
            amount=Decimal("200"),
            sub_ledger="AWS Production",
        ),
    ]
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        chart_of_accounts=[
            ChartOfAccountEntry(
                code="6110",
                name="Cloud Hosting Expense",
                type="Expense",
                sub_ledgers=[{"code": "01", "name": "AWS Production"}],
            ),
            ChartOfAccountEntry(code="1400", name="Tax Paid", type="Asset"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )
    lines = generate_entries(
        inv,
        AccountMapping("6110", "Cloud Hosting Expense"),
        config=config,
    )
    assert is_balanced(lines)
    by_code = {ln.account_code: ln.debit for ln in lines if ln.debit > 0}
    assert by_code["6110-01"] == Decimal("200")
    assert by_code["6110"] == Decimal("50")
