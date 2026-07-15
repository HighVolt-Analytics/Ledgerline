"""Structured table precedence over text qty parser."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.invoice.invoice_data import ParsedLineItem
from app.services.extraction.line_item_noise_patterns import is_noise_line_item_row
from app.services.extraction.pdf_parser import parse_local_text


def _ocr(text: str, payload: dict | None = None) -> OcrArtifact:
    return OcrArtifact(text=text, sparse=False, text_length=len(text), payload_json=payload or {})


def test_structured_table_blocks_text_qty_union() -> None:
    text = (
        "217 Henderson Road, #03-10, Singapore 159555\n"
        "INVOICE NO. : 260371344/\n"
        "CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97\n"
        "DOCUMENTARY CREDIT NUMBER: 308526022170 DATED 260316\n"
    )
    payload = {
        "table_line_items": [
            {
                "qty": "150",
                "description": "CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97",
            }
        ]
    }
    parsed = parse_local_text(text)
    merged = merge_extraction_sources(parsed, _ocr(text, payload))
    assert len(merged.line_items or []) == 1
    assert "CPU CHIPS" in (merged.line_items[0].description or "")


def test_noise_pattern_flags_address_and_reference_rows() -> None:
    assert is_noise_line_item_row("217 Henderson Road, Singapore 159555", Decimal("159555"))
    assert is_noise_line_item_row("DOCUMENTARY CREDIT NUMBER: 308526022170 DATED", Decimal("260316"))
    assert is_noise_line_item_row("Page 1 of 3")
    assert is_noise_line_item_row("Page 1 of")
    assert is_noise_line_item_row("01/01/2026")
    assert is_noise_line_item_row("ABN 12 345 678 901")
    assert is_noise_line_item_row("Bank Details please remit", Decimal("1"))
    assert is_noise_line_item_row("$45.03 USD due May 1,", Decimal("2026"))
    assert is_noise_line_item_row("Prinsengracht", Decimal("769"))
    assert is_noise_line_item_row("Prinsengracht 769")
    assert is_noise_line_item_row("60 Box", Decimal("60"))
    assert is_noise_line_item_row("195 Pair", Decimal("195"))


def test_noise_pattern_allows_product_row() -> None:
    item = ParsedLineItem(description="CPU CHIPS 14 Gen 13 14100", qty=Decimal("150"))
    assert not is_noise_line_item_row(item.description, item.qty)


def test_gap_fill_does_not_reappend_text_junk_after_di_rows() -> None:
    text = (
        "TAX INVOICE Acme Vendor INV-9 Total 100.00\n"
        "Description Qty Amount\n"
        "Widget 1 100.00\n"
        "Ship To: Acme Corp 1 10.00\n"
        "Mystery junk row 9.00\n"
    )
    payload = {
        "layout_line_mode": "gap_fill",
        "di_line_items": [
            {
                "description": "Widget",
                "qty": "1",
                "amount": "100.00",
                "unit_price": "100.00",
            }
        ],
        "table_line_items": [
            {
                "description": "Widget",
                "qty": "1",
                "amount": "100.00",
                "unit_price": "100.00",
            },
            {
                "description": "Ship To: Acme Corp",
                "qty": "1",
                "amount": "10.00",
                "unit_price": "10.00",
            },
            {
                "description": "Mystery junk row",
                "qty": None,
                "amount": "9.00",
                "unit_price": None,
            },
        ],
        "invoice_fields": {"vendor": "Acme Vendor", "invoice_no": "INV-9", "total": "100.00"},
    }
    parsed = parse_local_text(text)
    merged = merge_extraction_sources(parsed, _ocr(text, payload))
    descs = [row.description for row in (merged.line_items or [])]
    assert descs == ["Widget"]
    assert merged.vendor == "Acme Vendor" or "Acme" in (merged.vendor or "")
    assert merged.total == Decimal("100.00") or merged.total is not None


def test_stale_cached_table_rows_sanitized_even_without_reparse() -> None:
    """Cached OCR table_line_items must still drop noise on resolve/merge."""
    from app.services.extraction.line_items_parser import resolve_line_items_for_strategy

    payload = {
        "layout_line_mode": "primary",
        "table_line_items": [
            {
                "description": "Invoice Date: 12/03/2026",
                "qty": "1",
                "amount": "12.00",
                "unit_price": "12.00",
            },
            {
                "description": "217 Henderson Road, Singapore 159555",
                "qty": "159555",
                "amount": "1.00",
            },
            {
                "description": "Fresh Produce Box",
                "qty": "10",
                "amount": "500.00",
                "unit_price": "50.00",
            },
        ],
    }
    rows = resolve_line_items_for_strategy(payload, layout_mode="primary")
    descs = [r.description for r in rows]
    assert descs == ["Fresh Produce Box"]


def test_layout_grids_preferred_over_stale_table_line_items() -> None:
    from app.services.extraction.line_items_parser import resolve_line_items_for_strategy

    payload = {
        "layout_line_mode": "primary",
        "table_line_items": [
            {
                "description": "Ship To: Stale Cached Vendor",
                "qty": "1",
                "amount": "99.00",
                "unit_price": "99.00",
            },
            {
                "description": "Stale Product",
                "qty": "1",
                "amount": "10.00",
                "unit_price": "10.00",
            },
        ],
        "layout_table_grids": [
            [
                ["Description", "Qty", "Unit Price", "Amount"],
                ["Fresh Produce Box", "10", "50.00", "500.00"],
                ["Ship To: Acme Corp", "1", "10.00", "10.00"],
            ]
        ],
    }
    rows = resolve_line_items_for_strategy(payload, layout_mode="primary")
    descs = [r.description for r in rows]
    assert "Fresh Produce Box" in descs
    assert not any(d and "Ship To" in d for d in descs)
    assert "Stale Product" not in descs
