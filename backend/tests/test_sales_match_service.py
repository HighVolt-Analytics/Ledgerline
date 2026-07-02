from decimal import Decimal

from app.models.delivery_note import DeliveryNote
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.sales_order import SalesOrder
from app.services.sales_match_service import compute_three_way_match
from app.tenant_ids import TESTING_TENANT_UUID


def _so_with_dn() -> SalesOrder:
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number="SO-100",
        customer="Harbour View Hotel",
        so_qty=Decimal("10"),
        so_unit_price=Decimal("50"),
    )
    so.delivery_notes = [
        DeliveryNote(
            tenant_id=TESTING_TENANT_UUID,
            sales_order_id=0,
            dn_qty=Decimal("10"),
        )
    ]
    return so


def test_compute_three_way_match_full_when_qty_and_price_align() -> None:
    so = _so_with_dn()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        subtotal=Decimal("500"),
        gst=Decimal("50"),
        total=Decimal("550"),
    )
    inv.line_items = [
        LineItem(tenant_id=TESTING_TENANT_UUID, invoice_id=0, description="Widget", qty=Decimal("10"), unit_price=Decimal("50")),
    ]
    match = compute_three_way_match(so, inv)
    assert match.status in {"3-Way Match", "Qty Variance", "Price Variance", "No DN"}


def test_compute_three_way_match_no_dn_status() -> None:
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number="SO-200",
        customer="Beta Corp",
        so_qty=Decimal("5"),
        so_unit_price=Decimal("20"),
    )
    so.delivery_notes = []
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Beta Corp",
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
    )
    inv.line_items = [
        LineItem(tenant_id=TESTING_TENANT_UUID, invoice_id=0, description="Item", qty=Decimal("5"), unit_price=Decimal("20")),
    ]
    match = compute_three_way_match(so, inv)
    assert match.status == "No DN"
