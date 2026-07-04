"""OCR label-value fallback for tenant custom extraction fields."""

from __future__ import annotations

from app.services.extraction.custom_field_ocr_extractors import extract_custom_fields_from_text


def test_extract_contract_party_from_labeled_line() -> None:
    text = "MASTER SERVICES AGREEMENT\nContract Party: Permagen Planting Land Pty Ltd\n"
    found = extract_custom_fields_from_text(text, ["contract_party"])
    assert found["contract_party"] == "Permagen Planting Land Pty Ltd"


def test_extract_contract_party_case_insensitive_label() -> None:
    text = "CONTRACT_PARTY: Acme Co"
    found = extract_custom_fields_from_text(text, ["contract_party"])
    assert found["contract_party"] == "Acme Co"


def test_extract_skips_unknown_keys() -> None:
    assert extract_custom_fields_from_text("Vendor: Acme", ["contract_party"]) == {}


def test_extract_empty_input() -> None:
    assert extract_custom_fields_from_text("", ["contract_party"]) == {}
    assert extract_custom_fields_from_text("Contract Party: X", []) == {}
