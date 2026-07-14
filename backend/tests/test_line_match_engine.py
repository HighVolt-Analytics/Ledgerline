"""Unit tests for line-level three-way / two-way match engine."""

from __future__ import annotations

from decimal import Decimal

from app.models.delivery_note import DeliveryNote
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.sales_order import SalesOrder
from app.models.sales_order_line import SalesOrderLine
from app.services.matching.line_match_engine import (
    MatchLineInput,
    compute_line_match,
    pair_order_to_invoice,
)
from app.services.purchase.purchase_match_service import compute_three_way_match as compute_purchase_match
from app.services.sales.sales_match_service import compute_three_way_match as compute_sales_match
from app.tenant_ids import TESTING_TENANT_UUID


def test_pair_by_sku_then_description() -> None:
    orders = [
        MatchLineInput(key=1, description="Widget A", sku="WA-1", qty=Decimal("2"), unit_price=Decimal("10")),
        MatchLineInput(key=2, description="Widget B", sku="WB-1", qty=Decimal("3"), unit_price=Decimal("20")),
    ]
    inv = [
        MatchLineInput(key=10, description="widget b deluxe", sku="WB-1", qty=Decimal("3"), unit_price=Decimal("20")),
        MatchLineInput(key=11, description="Widget A", sku=None, qty=Decimal("2"), unit_price=Decimal("10")),
    ]
    paired, leftover_o, leftover_i = pair_order_to_invoice(orders, inv)
    assert len(paired) == 2
    assert not leftover_o
    assert not leftover_i


def test_multiline_full_match() -> None:
    rollup = compute_line_match(
        order_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
            MatchLineInput(key=2, description="B", sku="B", qty=Decimal("5"), unit_price=Decimal("4"), uom="EA"),
        ],
        invoice_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
            MatchLineInput(key=2, description="B", sku="B", qty=Decimal("5"), unit_price=Decimal("4"), uom="EA"),
        ],
        received_qty_by_order_key={1: Decimal("2"), 2: Decimal("5")},
        require_receipt=True,
        receipt_present=True,
    )
    assert rollup.status == "3-Way Match"
    assert rollup.qty_variance_value == 0.0
    assert rollup.price_variance_value == 0.0


def test_partial_bill_allowed() -> None:
    rollup = compute_line_match(
        order_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
            MatchLineInput(key=2, description="B", sku="B", qty=Decimal("5"), unit_price=Decimal("4"), uom="EA"),
            MatchLineInput(key=3, description="C", sku="C", qty=Decimal("1"), unit_price=Decimal("9"), uom="EA"),
        ],
        invoice_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
            MatchLineInput(key=2, description="B", sku="B", qty=Decimal("5"), unit_price=Decimal("4"), uom="EA"),
        ],
        received_qty_by_order_key={1: Decimal("2"), 2: Decimal("5"), 3: Decimal("1")},
        require_receipt=True,
        receipt_present=True,
    )
    assert rollup.status == "3-Way Match"
    assert any(r.status == "order_only" for r in rollup.line_results)


def test_unmatched_invoice_line_is_qty_variance() -> None:
    rollup = compute_line_match(
        order_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
        ],
        invoice_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
            MatchLineInput(key=2, description="Extra", sku="X", qty=Decimal("1"), unit_price=Decimal("50"), uom="EA"),
        ],
        received_qty_by_order_key={1: Decimal("2")},
        require_receipt=True,
        receipt_present=True,
    )
    assert rollup.status == "Qty Variance"
    assert any(r.status == "unmatched_invoice" for r in rollup.line_results)


def test_price_variance_on_one_line() -> None:
    rollup = compute_line_match(
        order_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
        ],
        invoice_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("12"), uom="EA"),
        ],
        received_qty_by_order_key={1: Decimal("2")},
        require_receipt=True,
        receipt_present=True,
    )
    assert rollup.status == "Price Variance"
    assert rollup.price_variance_value == 4.0


def test_multi_grn_summed() -> None:
    rollup = compute_line_match(
        order_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("10"), unit_price=Decimal("5"), uom="EA"),
        ],
        invoice_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("10"), unit_price=Decimal("5"), uom="EA"),
        ],
        received_qty_by_order_key={1: Decimal("4") + Decimal("6")},
        require_receipt=True,
        receipt_present=True,
    )
    assert rollup.status == "3-Way Match"


def test_missing_qty_is_variance() -> None:
    rollup = compute_line_match(
        order_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="EA"),
        ],
        invoice_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=None, unit_price=Decimal("10"), uom="EA"),
        ],
        received_qty_by_order_key={1: Decimal("2")},
        require_receipt=True,
        receipt_present=True,
    )
    assert rollup.status == "Qty Variance"
    assert any(r.status == "missing_qty" for r in rollup.line_results)


def test_uom_mismatch_is_variance() -> None:
    rollup = compute_line_match(
        order_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="KG"),
        ],
        invoice_lines=[
            MatchLineInput(key=1, description="A", sku="A", qty=Decimal("2"), unit_price=Decimal("10"), uom="LB"),
        ],
        received_qty_by_order_key={1: Decimal("2")},
        require_receipt=True,
        receipt_present=True,
    )
    assert rollup.status == "Qty Variance"
    assert any(r.status == "uom_mismatch" for r in rollup.line_results)


def test_purchase_header_only_backfill_path() -> None:
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-1",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("50"),
        item="Widgets",
        goods_receipts=[
            GoodsReceipt(
                tenant_id=TESTING_TENANT_UUID,
                purchase_order_id=0,
                grn_qty=Decimal("10"),
            )
        ],
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-1",
        subtotal=Decimal("500"),
        line_items=[
            LineItem(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=0,
                description="Widgets",
                qty=Decimal("10"),
                unit_price=Decimal("50"),
                amount=Decimal("500"),
            )
        ],
    )
    match = compute_purchase_match(po, inv)
    assert match.status == "3-Way Match"
    assert match.line_results
    assert po.lines  # synthesized


def test_sales_multiline_via_so_lines() -> None:
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number="SO-1",
        so_qty=Decimal("0"),
        so_unit_price=Decimal("0"),
    )
    so.lines = [
        SalesOrderLine(
            tenant_id=TESTING_TENANT_UUID,
            sales_order_id=0,
            line_no=1,
            description="A",
            sku="A",
            qty=Decimal("2"),
            unit_price=Decimal("10"),
            line_value=Decimal("20"),
            uom="EA",
        ),
        SalesOrderLine(
            tenant_id=TESTING_TENANT_UUID,
            sales_order_id=0,
            line_no=2,
            description="B",
            sku="B",
            qty=Decimal("3"),
            unit_price=Decimal("5"),
            line_value=Decimal("15"),
            uom="EA",
        ),
    ]
    so.delivery_notes = [
        DeliveryNote(
            tenant_id=TESTING_TENANT_UUID,
            sales_order_id=0,
            dn_qty=Decimal("5"),
        )
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="S-1",
        subtotal=Decimal("35"),
        line_items=[
            LineItem(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=0,
                description="A",
                sku="A",
                qty=Decimal("2"),
                unit_price=Decimal("10"),
                amount=Decimal("20"),
                uom="EA",
            ),
            LineItem(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=0,
                description="B",
                sku="B",
                qty=Decimal("3"),
                unit_price=Decimal("5"),
                amount=Decimal("15"),
                uom="EA",
            ),
        ],
    )
    match = compute_sales_match(so, inv)
    assert match.status == "3-Way Match"
    assert len(match.line_results) >= 2


def test_purchase_with_explicit_po_lines_and_two_grns() -> None:
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-ML",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("5"),
    )
    po.lines = [
        PurchaseOrderLine(
            tenant_id=TESTING_TENANT_UUID,
            purchase_order_id=0,
            line_no=1,
            description="A",
            sku="A",
            qty=Decimal("10"),
            unit_price=Decimal("5"),
            line_value=Decimal("50"),
            uom="EA",
        )
    ]
    po.goods_receipts = [
        GoodsReceipt(tenant_id=TESTING_TENANT_UUID, purchase_order_id=0, grn_qty=Decimal("4")),
        GoodsReceipt(tenant_id=TESTING_TENANT_UUID, purchase_order_id=0, grn_qty=Decimal("6")),
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-ML",
        subtotal=Decimal("50"),
        line_items=[
            LineItem(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=0,
                description="A",
                sku="A",
                qty=Decimal("10"),
                unit_price=Decimal("5"),
                amount=Decimal("50"),
                uom="EA",
            )
        ],
    )
    match = compute_purchase_match(po, inv)
    assert match.status == "3-Way Match"
