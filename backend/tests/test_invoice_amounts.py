from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.invoice.invoice_amounts import invoice_payable_total, resolve_invoice_amounts
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
