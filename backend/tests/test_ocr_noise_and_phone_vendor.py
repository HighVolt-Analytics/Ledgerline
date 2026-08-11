"""Tests for OCR-noise line descriptions and phone-as-vendor rejection."""

from __future__ import annotations

from decimal import Decimal

from app.services.extraction.line_item_skip_patterns import is_ocr_noise_line_description
from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.invoice.invoice_data import ParsedLineItem
from app.services.master_data.vendor_name_utils import is_plausible_vendor_name


def test_digit_colon_codes_are_ocr_noise() -> None:
    assert is_ocr_noise_line_description("005422: 27054") is True
    assert is_ocr_noise_line_description("1234-5678") is True
    assert is_ocr_noise_line_description("209") is True
    assert is_ocr_noise_line_description("12") is True
    assert is_ocr_noise_line_description("Shan silk scarf") is False
    assert is_ocr_noise_line_description("Office chair Model X") is False


def test_sanitize_blanks_noise_but_keeps_money_row() -> None:
    rows = sanitize_line_items(
        [
            ParsedLineItem(
                description="005422: 27054",
                qty=Decimal("1"),
                amount=Decimal("58000"),
            )
        ]
    )
    assert len(rows) == 1
    assert not (rows[0].description or "").strip()
    assert rows[0].amount == Decimal("58000")


def test_sanitize_blanks_short_digit_description() -> None:
    rows = sanitize_line_items(
        [
            ParsedLineItem(
                description="209",
                qty=Decimal("3"),
                amount=Decimal("100000"),
            )
        ]
    )
    assert len(rows) == 1
    assert not (rows[0].description or "").strip()
    assert rows[0].qty == Decimal("3")
    assert rows[0].amount == Decimal("100000")


def test_amount_sanity_clears_derived_fractional_unit_price() -> None:
    from app.services.shared.amount_sanity import sanitize_parsed_line_item

    cleaned = sanitize_parsed_line_item(
        ParsedLineItem(
            description="item",
            qty=Decimal("3"),
            unit_price=Decimal("33333.3333"),
            amount=Decimal("100000"),
        )
    )
    assert cleaned.unit_price is None
    assert cleaned.amount == Decimal("100000")
    assert cleaned.qty == Decimal("3")


def test_vision_header_keeps_amount_only_line_equal_to_total() -> None:
    from app.services.invoice.vision_header_extract import _parse_header_line_items

    rows = _parse_header_line_items(
        {
            "line_items": [
                {"description": "005422: 27054", "amount": 58000, "qty": 1},
            ]
        },
        total=Decimal("58000"),
    )
    assert len(rows) == 1
    assert rows[0].amount == Decimal("58000")
    assert not (rows[0].description or "").strip()


def test_phone_not_plausible_vendor() -> None:
    assert not is_plausible_vendor_name("Tel : 09 899 994 402")
    assert not is_plausible_vendor_name("Telephone No. +95 1 234 567")
    assert not is_plausible_vendor_name("32025")
    assert is_plausible_vendor_name("Junction City Traders")


def test_harvest_rejects_llm_employee_name() -> None:
    from app.services.extraction.extraction_field_values import (
        harvest_configured_fields_from_llm_raw,
        harvest_custom_fields_from_llm_raw,
    )

    harvested = harvest_configured_fields_from_llm_raw(
        {
            "employee_name": "Dr. Sai Kyaw Tayca",
            "extracted_fields": {
                "employee_name": "Dr. Sai Kyaw Tayca",
                "claim_notes": "Taxi fare",
            },
        },
        selected_keys=["employee_name", "claim_notes"],
    )
    assert "employee_name" not in harvested
    assert harvested.get("claim_notes") == "Taxi fare"

    custom = harvest_custom_fields_from_llm_raw(
        {
            "employee_name": "Dr. Sai Kyaw Tayca",
            "extracted_fields": {"employee_name": "OCR customer"},
        },
        selected_keys=["employee_name", "vendor"],
    )
    assert "employee_name" not in custom
