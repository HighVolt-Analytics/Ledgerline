from decimal import Decimal
from types import SimpleNamespace

from app.services.extraction.line_items_fallback_service import (
    FALLBACK_GRN_QTY,
    FALLBACK_HEADER,
    apply_line_items_fallback,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def _dt(role: str = "") -> SimpleNamespace:
    return SimpleNamespace(purchase_bundle_role=role)


def test_header_lump_sum_fallback_when_no_table() -> None:
    parsed = InvoiceData(
        vendor="Cloud Services Inc",
        subtotal=Decimal("499"),
        total=Decimal("548.90"),
        gst=Decimal("49.90"),
        document_text="TAX INVOICE\nMonthly subscription\nAmount Due: $499.00",
    )
    updated, tier = apply_line_items_fallback(parsed, dt_definition=_dt())
    assert tier == FALLBACK_HEADER
    assert len(updated.line_items) == 1
    assert updated.line_items[0].amount == Decimal("499")
    assert updated.line_items[0].source == FALLBACK_HEADER


def test_no_fallback_when_lines_already_present() -> None:
    parsed = InvoiceData(
        subtotal=Decimal("100"),
        line_items=[ParsedLineItem(description="Widget", qty=Decimal("1"), amount=Decimal("100"))],
    )
    updated, tier = apply_line_items_fallback(parsed)
    assert tier is None
    assert len(updated.line_items) == 1


def test_grn_qty_fallback_from_text() -> None:
    text = """
GOODS RECEIPT NOTE
PO Reference: PO-TEST-2026-001
Item Description          Qty Received
Fresh Produce Mixed Box   10
"""
    parsed = InvoiceData(document_text=text)
    updated, tier = apply_line_items_fallback(
        parsed,
        ocr_text=text,
        dt_definition=_dt("grn"),
    )
    assert tier in {FALLBACK_GRN_QTY, "fallback_structured"}
    assert updated.line_items
    assert any((row.qty or Decimal("0")) >= Decimal("10") for row in updated.line_items)


def test_structured_retry_when_table_present() -> None:
    text = """
INVOICE
Description                Qty   Unit Price   Amount
Fresh Produce Mixed Box    10      50.00      500.00
Subtotal                                          500.00
GST                                                50.00
Total                                             550.00
"""
    parsed = InvoiceData(
        subtotal=Decimal("500"),
        gst=Decimal("50"),
        total=Decimal("550"),
        document_text=text,
    )
    updated, tier = apply_line_items_fallback(parsed, ocr_text=text)
    assert tier == "fallback_structured"
    assert len(updated.line_items) >= 1
    assert updated.line_items[0].amount == Decimal("500")
