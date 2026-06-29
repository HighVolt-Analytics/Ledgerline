"""Three-way match with UOM conversion (cartons vs units)."""

from decimal import Decimal

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.schemas.uom_conversion import PurchaseMatchConfig, UomConversionRule
from app.services.purchase_match_service import compute_three_way_match
from app.services.uom_conversion_service import (
    convert_qty_to_base,
    infer_uom_from_description,
    normalize_uom_token,
)


def _match_config() -> PurchaseMatchConfig:
    return PurchaseMatchConfig(
        base_uom="EA",
        qty_tolerance_pct=0.0,
        uom_conversions=[
            UomConversionRule(
                id="ctn-ea",
                vendorKey="sysco-foods-australia-pty-ltd",
                fromUom="CTN",
                toUom="EA",
                factor=Decimal("12"),
            ),
            UomConversionRule(
                id="ctn-ea-global",
                vendorKey="",
                fromUom="CTN",
                toUom="EA",
                factor=Decimal("12"),
            ),
        ],
    )


def test_normalize_uom_aliases() -> None:
    assert normalize_uom_token("cartons") == "CTN"
    assert normalize_uom_token("units") == "EA"
    assert infer_uom_from_description("Fresh produce 10 cartons") == "CTN"


def test_carton_to_ea_conversion() -> None:
    cfg = _match_config()
    assert convert_qty_to_base(
        Decimal("10"), "CTN", vendor="Sysco Foods Australia Pty Ltd", config=cfg
    ) == Decimal("120")
    assert convert_qty_to_base(
        Decimal("120"), "units", vendor="Sysco Foods Australia Pty Ltd", config=cfg
    ) == Decimal("120")


def test_three_way_match_equivalent_uom_no_false_variance() -> None:
    """PO 10 cartons, invoice 120 units, GRN 10 cartons — all equal in base EA."""
    cfg = _match_config()
    po = PurchaseOrder(
        tenant_id=1,
        po_number="PO-DEMO-2001",
        vendor="Sysco Foods Australia Pty Ltd",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("60"),
        po_uom="CTN",
    )
    po.goods_receipts = [
        GoodsReceipt(purchase_order_id=1, grn_qty=Decimal("10"), grn_uom="CTN")
    ]
    inv = Invoice(
        tenant_id=1,
        vendor="Sysco Foods Australia Pty Ltd",
        po_reference="PO-DEMO-2001",
        subtotal=Decimal("600.00"),
        gst=Decimal("60.00"),
        total=Decimal("660.00"),
    )
    inv.line_items = [
        LineItem(
            invoice_id=1,
            description="Fresh produce",
            qty=Decimal("120"),
            uom="EA",
            unit_price=Decimal("5"),
            amount=Decimal("600"),
        )
    ]

    match = compute_three_way_match(po, inv, match_config=cfg)
    assert match.status == "3-Way Match"
    assert match.qty_variance_value == 0


def test_three_way_match_partial_receipt_qty_variance() -> None:
    """PO 10 CTN, invoice 120 EA (10 CTN), GRN 9 CTN — 1 CTN over-billing vs receipt."""
    cfg = _match_config()
    po = PurchaseOrder(
        tenant_id=1,
        po_number="PO-DEMO-2001",
        vendor="Sysco Foods Australia Pty Ltd",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("60"),
        po_uom="CTN",
    )
    po.goods_receipts = [
        GoodsReceipt(
            purchase_order_id=1,
            grn_qty=Decimal("9"),
            grn_uom="CTN",
            condition_note="1 carton damaged",
        )
    ]
    inv = Invoice(
        tenant_id=1,
        vendor="Sysco Foods Australia Pty Ltd",
        po_reference="PO-DEMO-2001",
        subtotal=Decimal("600.00"),
        total=Decimal("660.00"),
    )
    inv.line_items = [
        LineItem(
            invoice_id=1,
            qty=Decimal("120"),
            uom="EA",
            unit_price=Decimal("5"),
            amount=Decimal("600"),
        )
    ]

    match = compute_three_way_match(po, inv, match_config=cfg)
    assert match.status == "Qty Variance"
    assert match.qty_variance_value > 0


def test_three_way_match_invoice_matches_grn_after_uom() -> None:
    """Invoice 108 EA matches GRN 9 CTN (108 EA) — clean match."""
    cfg = _match_config()
    po = PurchaseOrder(
        tenant_id=1,
        po_number="PO-DEMO-2001",
        vendor="Sysco Foods Australia Pty Ltd",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("60"),
        po_uom="CTN",
    )
    po.goods_receipts = [
        GoodsReceipt(purchase_order_id=1, grn_qty=Decimal("9"), grn_uom="CTN")
    ]
    inv = Invoice(
        tenant_id=1,
        vendor="Sysco Foods Australia Pty Ltd",
        subtotal=Decimal("540.00"),
        total=Decimal("594.00"),
    )
    inv.line_items = [
        LineItem(
            invoice_id=1,
            qty=Decimal("108"),
            uom="EA",
            unit_price=Decimal("5"),
            amount=Decimal("540"),
        )
    ]

    match = compute_three_way_match(po, inv, match_config=cfg)
    assert match.status == "3-Way Match"
