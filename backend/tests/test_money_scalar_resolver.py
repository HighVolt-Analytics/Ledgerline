"""Registry-driven money scalar extraction tests."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.document_layout import DocumentLayoutResult, LayoutTable, LayoutTableCell
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.finance_field_labels import label_matches_field
from app.services.extraction.money_scalar_resolver import (
    extract_money_scalars_from_payload_tables,
    extract_money_scalars_from_tables,
    extract_money_scalars_from_text,
)
from app.services.invoice.invoice_data import InvoiceData


def test_label_matches_balance_due_as_total() -> None:
    assert label_matches_field("Balance due", "total")
    assert label_matches_field("Amount Due", "total")
    assert not label_matches_field("Subtotal", "total")


def test_extract_money_multiline_balance_due() -> None:
    text = (
        "Highvolt Pty Ltd\n"
        "Invoice No: QF-BOOK-3318745\n"
        "Line items here\n"
        "Balance due\n"
        "1,234.56\n"
    )
    found = extract_money_scalars_from_text(text)
    assert found.get("total") == Decimal("1234.56")


def test_extract_money_tail_window_total() -> None:
    padding = "header " * 200
    text = f"{padding}\nBalance Due\n999.00"
    found = extract_money_scalars_from_text(text)
    assert found.get("total") == Decimal("999.00")


def test_extract_money_from_table_footer() -> None:
    layout = DocumentLayoutResult(
        tables=(
            LayoutTable(
                page_index=0,
                row_count=3,
                column_count=2,
                cells=(
                    LayoutTableCell("Description", 0, 0),
                    LayoutTableCell("Amount", 0, 1),
                    LayoutTableCell("Widget", 1, 0),
                    LayoutTableCell("100.00", 1, 1),
                    LayoutTableCell("Balance due", 2, 0),
                    LayoutTableCell("110.00", 2, 1),
                ),
            ),
        )
    )
    found = extract_money_scalars_from_tables(layout)
    assert found.get("total") == Decimal("110.00")


def test_extract_money_from_payload_table_grids() -> None:
    payload = {
        "layout_table_grids": [
            [
                ["Item", "Amount"],
                ["Service", "50.00"],
                ["Subtotal", "50.00"],
                ["GST", "5.00"],
                ["Total", "55.00"],
            ]
        ]
    }
    found = extract_money_scalars_from_payload_tables(payload)
    assert found.get("subtotal") == Decimal("50.00")
    assert found.get("gst") == Decimal("5.00")
    assert found.get("total") == Decimal("55.00")


def test_extract_money_glued_currency_label() -> None:
    """Thermal POS receipt: 'SubtotalMMK 100,000' (no separator) must parse correctly."""
    text = (
        "FAMILY FLORAL GIFT SHOP\n"
        "TAX INVOICE\n"
        "Ref    #6931\n"
        "SubtotalMMK 100,000\n"
        "GST    MMK 0\n"
        "TOTALMMK 100,000\n"
    )
    found = extract_money_scalars_from_text(text)
    assert found.get("subtotal") == Decimal("100000")
    assert found.get("total") == Decimal("100000")


def test_merge_extraction_sources_fills_total_from_text() -> None:
    text = "Vendor: Acme\nInvoice No: INV-1\nBalance due\n500.00"
    ocr = OcrArtifact(success=True, text=text, text_length=len(text))
    parsed = InvoiceData(document_text=text)
    merged = merge_extraction_sources(parsed, ocr)
    assert merged.total == Decimal("500.00")
