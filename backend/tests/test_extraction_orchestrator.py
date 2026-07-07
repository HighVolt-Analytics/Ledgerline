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
