
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Validation behaviour for PO / GRN supporting documents."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.purchase_match_service import compute_three_way_match
from app.services.validation_runner import ValidationRunContext, run_configured_validations


@pytest.mark.asyncio
async def test_po_document_skips_vr02_duplicate_check(db_session: AsyncSession) -> None:
    data = InvoiceData(
        vendor="Sysco Australia",
        po_reference="PO-MKT-2026-JUN17",
        subtotal=Decimal("500.00"),
        total=Decimal("500.00"),
        line_items=[
            ParsedLineItem(
                description="Fresh seasonal produce",
                qty=Decimal("10"),
                unit_price=Decimal("50"),
                amount=Decimal("500"),
            )
        ],
    )
    ctx = ValidationRunContext(
        data=data,
        session=db_session,
        tenant_id=TESTING_TENANT_UUID,
        purchase_document_type="po",
    )
    results = await run_configured_validations(ctx)
    codes = {row.rule for row in results}
    assert "VR02" not in codes
    assert any(row.rule == "VR03" and row.passed for row in results)


def test_three_way_match_clean_after_grn_before_invoice_pending() -> None:
    """Invoice arriving after GRN should match when qty/price align (no false Routed for Approval)."""

    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-MKT-2026-JUN17",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("50"),
        status=PurchaseOrderStatus.VARIANCE_PENDING,
        variance_approved=False,
    )
    po.goods_receipts = [
        GoodsReceipt(purchase_order_id=1, grn_qty=Decimal("10"), grn_date=None)
    ]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia",
        po_reference="PO-MKT-2026-JUN17",
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
    )
    inv.line_items = [
        LineItem(
            invoice_id=1,
            description="Fresh seasonal produce",
            qty=Decimal("10"),
            unit_price=Decimal("50"),
            amount=Decimal("500"),
        )
    ]

    match = compute_three_way_match(po, inv)
    assert match.status == "3-Way Match"
    assert match.qty_variance_value == 0
    assert match.price_variance_value == 0
