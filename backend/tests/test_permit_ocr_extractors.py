"""Tests for permit OCR regex extraction."""

from __future__ import annotations

from app.services.extraction.permit_ocr_extractors import extract_permit_fields_from_text


def test_extract_permit_no_from_labelled_line() -> None:
    text = "CARGO CLEARANCE PERMIT\nPermit No: OD6E379991N\nConsignment Ref: ABC12345"
    fields = extract_permit_fields_from_text(text)
    assert fields.get("permit_no") == "OD6E379991N"
    assert fields.get("consignment_ref") == "ABC12345"


def test_extract_permit_no_empty_text() -> None:
    assert extract_permit_fields_from_text("") == {}
    assert extract_permit_fields_from_text(None) == {}
