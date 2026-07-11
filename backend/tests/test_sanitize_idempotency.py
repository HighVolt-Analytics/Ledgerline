"""Sanitize idempotency: double-sanitize vs merge-then-sanitize on fixtures A–F."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.extraction.extraction_orchestrator import _merge_line_items_from_sources
from app.services.extraction.line_items_parser import document_has_qty_only_table
from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.extraction.pdf_parser import parse_local_text
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _row_signature(item: ParsedLineItem) -> tuple:
    return (
        (item.description or "").strip().lower(),
        item.qty,
        item.unit_price,
        item.amount,
        item.tax_amount,
    )


def _assert_same_items(left: list[ParsedLineItem], right: list[ParsedLineItem]) -> None:
    assert [_row_signature(item) for item in left] == [_row_signature(item) for item in right]


def _sanitize_kwargs(parsed: InvoiceData, text: str, payload: dict) -> dict:
    allow_qty_only = document_has_qty_only_table(text, payload)
    return {
        "extracted_fields": parsed.extracted_fields,
        "vendor": parsed.vendor,
        "invoice_no": parsed.invoice_no,
        "po_reference": parsed.po_reference,
        "so_reference": (parsed.extracted_fields or {}).get("so_reference"),
        "cost_centre": parsed.cost_centre,
        "allow_qty_only": allow_qty_only,
    }


def _path_a(parsed: InvoiceData, text: str, payload: dict) -> list[ParsedLineItem]:
    kwargs = _sanitize_kwargs(parsed, text, payload)
    pre = sanitize_line_items(list(parsed.line_items), **kwargs)
    merged = _merge_line_items_from_sources(replace(parsed, line_items=pre), text, payload)
    return sanitize_line_items(merged, **kwargs)


def _path_b(parsed: InvoiceData, text: str, payload: dict) -> list[ParsedLineItem]:
    kwargs = _sanitize_kwargs(parsed, text, payload)
    merged = _merge_line_items_from_sources(parsed, text, payload)
    return sanitize_line_items(merged, **kwargs)


@pytest.mark.parametrize(
    ("parsed", "text", "payload"),
    [
        pytest.param(
            InvoiceData(
                line_items=[
                    ParsedLineItem(
                        description="Widget A",
                        qty=Decimal("2"),
                        unit_price=Decimal("10"),
                        amount=Decimal("20"),
                        source="llm",
                    ),
                ]
            ),
            "DESCRIPTION QTY UNIT PRICE AMOUNT\nWidget A 2 10.00 20.00\nWidget B 1 5.00 5.00\n",
            {
                "table_line_items": [
                    {"description": "Widget A", "qty": "2", "unit_price": "10", "amount": "20"},
                    {"description": "Widget B", "qty": "1", "unit_price": "5", "amount": "5"},
                ]
            },
            id="fixture_a_product_table",
        ),
        pytest.param(
            InvoiceData(
                line_items=[
                    ParsedLineItem(description="CPU CHIPS 14 Gen I3 14100", qty=Decimal("150"), source="llm"),
                ]
            ),
            (_FIXTURES_DIR / "qty_only_table_ocr.txt").read_text(encoding="utf-8"),
            {
                "table_line_items": [
                    {"description": "CPU CHIPS 14 Gen I3 14100", "qty": "150"},
                ]
            },
            id="fixture_b_qty_only",
        ),
        pytest.param(
            InvoiceData(
                line_items=[
                    ParsedLineItem(description="Freight", qty=Decimal("1"), amount=Decimal("400"), source="llm"),
                ]
            ),
            "COMMERCIAL INVOICE\nDESCRIPTION OF GOODS: COMPUTER PARTS\nFREIGHT: USD 400.00\n",
            {},
            id="fixture_c_charge_lines",
        ),
        pytest.param(
            InvoiceData(
                line_items=[ParsedLineItem(description="LLM Wrong", amount=Decimal("999"), source="llm")],
            ),
            "TAX INVOICE\nVendor: Acme\nTotal: 100.00\n",
            {},
            id="fixture_d_no_table",
        ),
        pytest.param(
            replace(
                parse_local_text(
                    "217 Henderson Road, Singapore 159555\n"
                    "CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97\n"
                ),
                line_items=[
                    ParsedLineItem(
                        description="CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97",
                        qty=Decimal("150"),
                        source="llm",
                    ),
                ],
            ),
            "217 Henderson Road, Singapore 159555\n"
            "CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97\n",
            {
                "table_line_items": [
                    {
                        "qty": "150",
                        "description": "CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97",
                    }
                ]
            },
            id="fixture_e_noise_anchor",
        ),
        pytest.param(
            InvoiceData(
                line_items=[
                    ParsedLineItem(description="Widget A", qty=Decimal("2"), unit_price=Decimal("10"), amount=Decimal("20"), source="llm"),
                    ParsedLineItem(description="Widget B", qty=Decimal("1"), unit_price=None, amount=Decimal("5"), source="llm"),
                ],
                raw_fields={"_line_items_confidence": 0.5},
            ),
            "DESCRIPTION QTY UNIT PRICE AMOUNT\nWidget A 2 10.00 20.00\nWidget B 1 5.00 5.00\n",
            {
                "table_line_items": [
                    {"description": "Widget A", "qty": "2", "unit_price": "10", "amount": "20"},
                    {"description": "Widget B", "qty": "1", "unit_price": "5", "amount": "5"},
                ]
            },
            id="fixture_f_partial_trust",
        ),
    ],
)
def test_sanitize_idempotency_paths_match(
    parsed: InvoiceData,
    text: str,
    payload: dict,
) -> None:
    _assert_same_items(_path_a(parsed, text, payload), _path_b(parsed, text, payload))
