from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.invoice.invoice_amounts import (
    backfill_invoice_amounts_from_sources,
    invoice_payable_total,
    resolve_invoice_amounts,
)
from app.services.payments.journal_generator import generate_entries, is_balanced
from app.services.rule_book.account_mapper import AccountMapping
from app.tenant_ids import TESTING_TENANT_UUID


def test_resolve_invoice_amounts_from_line_items() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 6, 24),
        subtotal=None,
        gst=Decimal("50"),
        total=None,
        status=InvoiceStatus.VALIDATING,
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
    subtotal, gst, total = resolve_invoice_amounts(inv)
    assert subtotal == Decimal("500")
    assert gst == Decimal("50")
    assert total == Decimal("550")
    assert invoice_payable_total(inv) == Decimal("550")


def test_resolve_prefers_total_minus_gst_over_tax_inclusive_lines() -> None:
    """Invoice 656 pattern: line dump includes CGST/SGST; header has gst + total."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2025, 11, 25),
        subtotal=None,
        gst=Decimal("55.92"),
        total=Decimal("9800.53"),
        status=InvoiceStatus.JOURNALING,
        currency="INR",
        route_target="Purchase Management",
    )
    inv.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="*Fare Charges",
            amount=Decimal("9434.00"),
        ),
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="Trip Assure Fee",
            amount=Decimal("310.62"),
        ),
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="CGST @9%",
            amount=Decimal("27.96"),
        ),
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="SGST @9%",
            amount=Decimal("27.96"),
        ),
    ]
    subtotal, gst, total = resolve_invoice_amounts(inv)
    assert total == Decimal("9800.53")
    assert gst == Decimal("55.92")
    assert subtotal == Decimal("9744.61")  # total − gst
    backfill_invoice_amounts_from_sources(inv)
    assert inv.subtotal == Decimal("9744.61")

    mapping = AccountMapping(account_code="6100", account_name="Operating Expenses")
    lines = generate_entries(inv, mapping)
    assert is_balanced(lines)


def test_line_items_subtotal_excludes_tax_rows_when_no_header_total() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2025, 11, 25),
        subtotal=None,
        gst=None,
        total=None,
        status=InvoiceStatus.VALIDATING,
        currency="INR",
    )
    inv.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="Trip Assure Fee",
            amount=Decimal("310.62"),
        ),
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="CGST @9%",
            amount=Decimal("27.96"),
        ),
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="SGST @9%",
            amount=Decimal("27.96"),
        ),
    ]
    subtotal, gst, total = resolve_invoice_amounts(inv)
    assert subtotal == Decimal("310.62")
    assert gst == Decimal("0")
    assert total == Decimal("310.62")


def test_resolve_prefers_line_sum_when_header_subtotal_disagrees() -> None:
    """Invoice 664 pattern: SGD subtotal on header, USD total + lines agree."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_date=date(2026, 5, 25),
        subtotal=Decimal("7712.47"),
        gst=Decimal("0"),
        total=Decimal("6031.00"),
        status=InvoiceStatus.JOURNALING,
        currency="USD",
        route_target="Purchase Management",
    )
    inv.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="Item A",
            amount=Decimal("3000.00"),
        ),
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            description="Item B",
            amount=Decimal("3031.00"),
        ),
    ]
    subtotal, gst, total = resolve_invoice_amounts(inv)
    assert subtotal == Decimal("6031.00")
    assert gst == Decimal("0")
    assert total == Decimal("6031.00")

    mapping = AccountMapping(account_code="6100", account_name="Operating Expenses")
    lines = generate_entries(inv, mapping)
    assert is_balanced(lines)
