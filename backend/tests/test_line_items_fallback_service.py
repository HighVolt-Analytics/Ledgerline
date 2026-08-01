from decimal import Decimal
from types import SimpleNamespace

from app.services.extraction.line_items_fallback_service import (
    FALLBACK_GRN_QTY,
    FALLBACK_PDF_TABLES,
    apply_line_items_fallback,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def _dt(role: str = "") -> SimpleNamespace:
    return SimpleNamespace(purchase_bundle_role=role)


def test_header_lump_sum_fallback_does_not_invent_line() -> None:
    """Grounded-only: header totals must not invent qty=1 / unit_price lines."""
    parsed = InvoiceData(
        vendor="Cloud Services Inc",
        subtotal=Decimal("499"),
        total=Decimal("548.90"),
        gst=Decimal("49.90"),
        document_text="TAX INVOICE\nMonthly subscription\nAmount Due: $499.00",
    )
    updated, tier = apply_line_items_fallback(parsed, dt_definition=_dt())
    assert tier is None
    assert updated.line_items == []


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


def test_structured_fallback_ignores_text_qty_bleed_when_di_money_present() -> None:
    text = (
        "Weaviate B.V.\nPrinsengracht 769\n"
        "Minimum amount Apr 1-Apr 30, 2026 1 44.61\n"
        "$45.03 USD due May 1, 2026\n"
        "Page 1 of 2\n"
    )
    payload = {
        "di_line_items": [
            {
                "description": "Minimum amount Apr 1-Apr 30, 2026",
                "qty": "1",
                "unit_price": "44.61",
                "amount": "44.61",
            },
            {
                "description": "Flex Shared - Storage GBs (backups)",
                "qty": "1",
                "unit_price": "0.02",
                "amount": "0.02",
            },
        ],
        "table_line_items": [
            {
                "description": "Minimum amount Apr 1-Apr 30, 2026",
                "qty": "1",
                "unit_price": "44.61",
                "amount": "44.61",
            }
        ],
    }
    parsed = InvoiceData(vendor="Weaviate B.V.", total=Decimal("45.03"), document_text=text)
    updated, tier = apply_line_items_fallback(parsed, ocr_text=text, ocr_payload=payload)
    assert tier == "fallback_structured"
    assert len(updated.line_items) == 2
    assert all(row.amount is not None for row in updated.line_items)
    assert not any("Prinsengracht" in (row.description or "") for row in updated.line_items)
    assert not any("due" in (row.description or "").lower() for row in updated.line_items)
    assert not any((row.description or "").lower().startswith("page") for row in updated.line_items)


def test_pdf_table_fallback_when_ocr_empty(monkeypatch, tmp_path) -> None:
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def _fake_pdf_rows(_path: str, **_kwargs):
        return [
            ParsedLineItem(
                description="Office chairs – ergonomic",
                qty=Decimal("10"),
                unit_price=Decimal("500.00"),
                amount=Decimal("5000.00"),
                source="table",
            )
        ]

    monkeypatch.setattr(
        "app.services.extraction.layout_field_extractor.parse_line_items_from_pdf_path",
        _fake_pdf_rows,
    )
    parsed = InvoiceData()
    updated, tier = apply_line_items_fallback(parsed, pdf_path=str(pdf))
    assert tier == FALLBACK_PDF_TABLES
    assert len(updated.line_items) == 1
    assert updated.line_items[0].amount == Decimal("5000.00")
    assert (updated.raw_fields or {}).get("_line_items_fallback") == FALLBACK_PDF_TABLES
