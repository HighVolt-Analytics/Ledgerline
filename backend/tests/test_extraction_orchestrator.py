"""Tests for unified extraction orchestrator."""

from datetime import date
from decimal import Decimal

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


APOLLO_TEXT = """
ZenLeads Inc. (dba Apollo.io)
Invoice Number EL1KAGEN-0012
Date of issue April 20, 2026
Date due April 20, 2026
Subtotal $23.71
Total $23.71 USD
"""


def test_merge_extraction_sources_apollo_dates() -> None:
    parsed = InvoiceData(
        vendor="ZenLeads Inc. (dba Apollo.io)",
        invoice_no="EL1KAGEN-0012",
        total=Decimal("23.71"),
    )
    ocr = OcrArtifact(
        success=True,
        text=APOLLO_TEXT,
        text_length=len(APOLLO_TEXT),
        layout_kv={"Date of issue": "April 20, 2026", "Date due": "April 20, 2026"},
        payload_json={
            "invoice_fields": {
                "vendor": "ZenLeads Inc. (dba Apollo.io)",
                "invoice_no": "EL1KAGEN-0012",
                "invoice_date": "2026-04-20",
                "due_date": "2026-04-20",
                "total": "23.71",
                "currency": "USD",
            }
        },
    )
    merged = merge_extraction_sources(parsed, ocr)
    assert merged.invoice_date == date(2026, 4, 20)
    assert merged.due_date == date(2026, 4, 20)


def test_merge_extraction_sources_soft_fills_di_when_untrusted() -> None:
    """DI-populated but untrusted scalars still gap-fill empty LLM fields."""
    text = (
        "TAX INVOICE\n"
        "Acme Trading Pty Ltd\n"
        "ABN 12 345 678 901\n"
        "Invoice Number: INV-4421\n"
        "Invoice Date: 11/03/2026\n"
        "Total AUD 250.00\n"
    )
    parsed = InvoiceData()  # empty LLM harvest
    ocr = OcrArtifact(
        success=True,
        text=text,
        text_length=len(text),
        payload_json={
            "invoice_fields": {
                "vendor": "Acme Trading Pty Ltd",
                "invoice_no": "INV-4421",
                "invoice_date": "2026-03-11",
                "total": "250.00",
                "currency": "AUD",
            },
            "di_scalar_sources": {
                "vendor": "VendorName",
                "invoice_no": "InvoiceId",
                "invoice_date": "InvoiceDate",
                "total": "InvoiceTotal",
                "currency": "CurrencyCode",
            },
        },
    )
    merged = merge_extraction_sources(parsed, ocr)
    assert merged.vendor == "Acme Trading Pty Ltd"
    assert merged.invoice_no == "INV-4421"
    assert merged.total == Decimal("250.00")
    assert merged.currency == "AUD"


def test_merge_extraction_sources_fills_from_raw_layout_kv_labels() -> None:
    """Azure layout_kv uses display labels; merge must map them to canonical keys."""
    parsed = InvoiceData()
    ocr = OcrArtifact(
        success=True,
        text="Tax Invoice\nInvoice No: INV-7788\nVendor: Acme Supplies\nTotal: 100.00\n",
        text_length=80,
        layout_kv={
            "Invoice No": "INV-7788",
            "Vendor Name": "Acme Supplies",
            "Invoice Date": "12/03/2026",
            "Total": "100.00",
        },
    )
    merged = merge_extraction_sources(parsed, ocr)
    assert merged.invoice_no == "INV-7788"
    assert merged.vendor and "Acme" in merged.vendor
    assert merged.total == Decimal("100.00")


def test_merge_extraction_sources_fills_from_regex_when_llm_empty() -> None:
    parsed = InvoiceData(vendor="ZenLeads Inc.")
    ocr = OcrArtifact(success=True, text=APOLLO_TEXT, text_length=len(APOLLO_TEXT))
    merged = merge_extraction_sources(parsed, ocr)
    assert merged.invoice_date == date(2026, 4, 20)
    assert merged.due_date == date(2026, 4, 20)
    assert merged.invoice_no == "EL1KAGEN-0012"


def test_merge_extraction_sources_enriches_partial_line_items() -> None:
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(description="Catering package", qty=Decimal("10"), unit_price=None, amount=None),
        ]
    )
    ocr = OcrArtifact(
        success=True,
        text="Catering package 10 50.00 500.00\n",
        text_length=32,
        payload_json={
            "table_line_items": [
                {
                    "description": "Catering package",
                    "qty": "10",
                    "unit_price": "50",
                    "amount": "500",
                }
            ]
        },
    )
    merged = merge_extraction_sources(parsed, ocr)
    assert len(merged.line_items) == 1
    assert merged.line_items[0].unit_price == Decimal("50")
    assert merged.line_items[0].amount == Decimal("500")


def test_merge_skips_regex_when_llm_line_items_trusted() -> None:
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(
                description="Catering package",
                qty=Decimal("10"),
                unit_price=Decimal("50"),
                amount=Decimal("500"),
            ),
        ]
    )
    ocr = OcrArtifact(
        success=True,
        text="Wrong Product 99 1.00 99.00\n",
        text_length=28,
        payload_json={
            "table_line_items": [
                {
                    "description": "Wrong Product",
                    "qty": "99",
                    "unit_price": "1",
                    "amount": "99",
                }
            ]
        },
    )
    merged = merge_extraction_sources(parsed, ocr)
    assert len(merged.line_items) == 1
    assert merged.line_items[0].description == "Catering package"
    assert merged.line_items[0].amount == Decimal("500")


def test_merge_unions_partial_llm_with_full_table() -> None:
    table_rows = [
        {"description": "Widget A", "qty": "2", "unit_price": "10", "amount": "20"},
        {"description": "Widget B", "qty": "1", "unit_price": "5", "amount": "5"},
        {"description": "Widget C", "qty": "3", "unit_price": "2", "amount": "6"},
        {"description": "Widget D", "qty": "1", "unit_price": "8", "amount": "8"},
        {"description": "Widget E", "qty": "2", "unit_price": "4", "amount": "8"},
    ]
    text = (
        "DESCRIPTION QTY UNIT PRICE AMOUNT\n"
        "Widget A 2 10.00 20.00\n"
        "Widget B 1 5.00 5.00\n"
        "Widget C 3 2.00 6.00\n"
        "Widget D 1 8.00 8.00\n"
        "Widget E 2 4.00 8.00\n"
    )
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(
                description="Widget A",
                qty=Decimal("2"),
                unit_price=Decimal("10"),
                amount=Decimal("20"),
            ),
            ParsedLineItem(
                description="Widget B",
                qty=Decimal("1"),
                unit_price=Decimal("5"),
                amount=Decimal("5"),
            ),
        ]
    )
    ocr = OcrArtifact(success=True, text=text, text_length=len(text), payload_json={"table_line_items": table_rows})
    merged = merge_extraction_sources(parsed, ocr)
    assert len(merged.line_items) == 5
    descriptions = {item.description for item in merged.line_items}
    assert "Widget C" in descriptions
    assert "Widget E" in descriptions


def test_trusted_llm_does_not_block_larger_table() -> None:
    table_rows = [
        {"description": f"Widget {label}", "qty": "1", "unit_price": "10", "amount": "10"}
        for label in ("A", "B", "C", "D", "E")
    ]
    text = "DESCRIPTION QTY UNIT PRICE AMOUNT\n" + "\n".join(
        f"Widget {label} 1 10.00 10.00" for label in ("A", "B", "C", "D", "E")
    )
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(
                description="Widget A",
                qty=Decimal("1"),
                unit_price=Decimal("10"),
                amount=Decimal("10"),
            ),
            ParsedLineItem(
                description="Widget B",
                qty=Decimal("1"),
                unit_price=Decimal("10"),
                amount=Decimal("10"),
            ),
        ]
    )
    ocr = OcrArtifact(success=True, text=text, text_length=len(text), payload_json={"table_line_items": table_rows})
    merged = merge_extraction_sources(parsed, ocr)
    assert len(merged.line_items) == 5


def test_partial_di_unions_with_qty_only_table() -> None:
    from pathlib import Path

    fixtures = Path(__file__).resolve().parent / "fixtures"
    text = (fixtures / "qty_only_table_ocr.txt").read_text(encoding="utf-8")
    table_rows = [
        {"description": "CPU CHIPS 14 Gen I3 14100", "qty": "150"},
        {"description": "CPU CHIPS 14 Gen I5 14400", "qty": "70"},
        {"description": "CPU CHIPS 14 Gen I5 14500", "qty": "130"},
        {"description": "CPU CHIPS 14 Gen I7 14700", "qty": "200"},
        {"description": "CPU CHIPS 14 Gen I9 14900", "qty": "10"},
    ]
    parsed = InvoiceData(line_items=[])
    ocr = OcrArtifact(
        success=True,
        text=text,
        text_length=len(text),
        payload_json={
            "di_line_items": [{"description": "PACKING LIST HEADER", "qty": "1"}],
            "table_line_items": table_rows,
        },
    )
    merged = merge_extraction_sources(parsed, ocr)
    assert len(merged.line_items) >= 5


def test_di_grounding_skip_keys_preserves_grounded_dates() -> None:
    from app.services.extraction.extraction_orchestrator import _di_grounding_skip_keys

    data = InvoiceData(invoice_date=date(2026, 4, 20), due_date=date(2026, 4, 20))
    skip = _di_grounding_skip_keys(
        data,
        APOLLO_TEXT,
        {"invoice_date", "due_date"},
    )
    assert skip == frozenset({"invoice_date", "due_date"})


def test_di_grounding_skip_keys_excludes_ungrounded_vendor() -> None:
    from app.services.extraction.extraction_orchestrator import _di_grounding_skip_keys

    data = InvoiceData(vendor="Hallucinated Vendor")
    skip = _di_grounding_skip_keys(
        data,
        "TAX INVOICE\nVendor: Real Co",
        {"vendor"},
    )
    assert "vendor" not in skip
