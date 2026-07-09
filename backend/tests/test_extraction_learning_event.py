"""Extraction learning event tests."""

from __future__ import annotations

from app.services.extraction.extraction_learning_event import build_learning_event


def test_learning_event_captures_correction() -> None:
    event = build_learning_event(
        org_id="org-1",
        dt_code="DT-01",
        field_key="invoice_no",
        before_value="INV-1",
        after_value="INV-100",
        ocr_snippet="Invoice No: INV-100",
        invoice_id=9,
    )
    assert event.after_value == "INV-100"
    assert event.invoice_id == 9
