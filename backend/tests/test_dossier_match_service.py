"""Dossier three-way match summary and pipeline checks."""

from decimal import Decimal

from app.models.goods_receipt import GoodsReceipt
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.schemas.purchase import ThreeWayMatchResult
from app.services.dossier_match_service import (
    build_dossier_match_summary,
    match_checks_from_summary,
    match_summary_from_audit_detail,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_build_dossier_match_summary_includes_variances() -> None:
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-2026-0457",
        po_qty=Decimal("1"),
        po_unit_price=Decimal("89500"),
        status=PurchaseOrderStatus.OPEN,
    )
    grn = GoodsReceipt(
        tenant_id=TESTING_TENANT_UUID,
        grn_qty=Decimal("1"),
        condition_note="Linked via invoice_no bridge",
    )
    po.goods_receipts = [grn]
    match = ThreeWayMatchResult(
        status="3-Way Match",
        qty_variance_value=0.0,
        price_variance_value=0.0,
        total_deviation=0.0,
        po_value=89500.0,
        invoice_value=89500.0,
        invoice_gst=16110.0,
        invoice_total=105610.0,
    )
    summary = build_dossier_match_summary(
        po_row=po,
        commercial=None,
        match=match,
        currency="AUD",
    )
    assert summary.po_value == 89500.0
    assert summary.invoice_total == 105610.0
    assert summary.total_deviation == 0.0
    assert summary.grn_condition == "Linked via invoice_no bridge"

    checks = match_checks_from_summary(summary)
    assert any(row.id == "match-deviation" and row.state == "pass" for row in checks)


def test_match_summary_from_audit_detail_round_trip() -> None:
    detail = {
        "match_status": "3-Way Match",
        "po_value": 89500.0,
        "po_qty": 1.0,
        "po_unit_price": 89500.0,
        "grn_present": True,
        "grn_qty": 1.0,
        "invoice_qty": 2800.0,
        "invoice_unit_price": 31.96,
        "invoice_value": 89500.0,
        "invoice_gst": 16110.0,
        "invoice_total": 105610.0,
        "qty_variance_value": 0.0,
        "price_variance_value": 0.0,
        "total_deviation": 0.0,
        "currency": "AUD",
    }
    summary = match_summary_from_audit_detail(detail, currency="AUD")
    assert summary is not None
    assert summary.invoice_qty == 2800.0
    assert summary.total_deviation == 0.0
