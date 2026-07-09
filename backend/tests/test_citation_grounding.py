"""Citation grounding verification tests."""

from __future__ import annotations

from app.schemas.llm_document import FieldCitation, LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.citation_grounding_service import (
    citation_audit_detail,
    verify_and_apply_citations,
    verify_field_citation,
)


def test_valid_citation_accepted() -> None:
    ocr_text = "Tax Invoice\nInvoice No: INV-100\nTotal: 500.00"
    result = verify_field_citation(
        "invoice_no",
        "INV-100",
        FieldCitation(snippet="INV-100", page=None),
        ocr_text=ocr_text,
    )
    assert result.verified is True


def test_hallucinated_snippet_rejected() -> None:
    ocr_text = "Tax Invoice\nInvoice No: INV-100"
    result = verify_field_citation(
        "invoice_no",
        "INV-999",
        FieldCitation(snippet="INV-999", page=None),
        ocr_text=ocr_text,
    )
    assert result.verified is False
    assert result.failure_reason == "snippet_not_in_ocr"


def test_line_items_citation_passes_with_per_row_ocr_match() -> None:
    ocr_text = """
PART MODEL QTY
CPU CHIPS 14 Gen I3 14100 I3-14100 150
CPU CHIPS 14 Gen I5 14400 I5-14400 70
"""
    rows = [
        {"description": "CPU CHIPS 14 Gen I3 14100", "qty": "150"},
        {"description": "CPU CHIPS 14 Gen I5 14400", "qty": "70"},
    ]
    result = verify_field_citation("line_items", rows, None, ocr_text=ocr_text)
    assert result.verified is True


def test_line_items_citation_fails_when_rows_not_in_ocr() -> None:
    result = verify_field_citation(
        "line_items",
        [{"description": "Missing widget", "qty": "1"}],
        None,
        ocr_text="Vendor: Acme Pty Ltd",
    )
    assert result.verified is False
    assert result.failure_reason == "missing_citation"


def test_missing_citation_rejected_for_value() -> None:
    result = verify_field_citation(
        "total",
        "100.00",
        None,
        ocr_text="Total 100.00",
    )
    assert result.verified is False
    assert result.failure_reason == "missing_citation"


def test_citation_failure_caps_confidence() -> None:
    ocr = OcrArtifact(success=True, text="Vendor: Acme Pty Ltd")
    llm = LlmDocumentResult(
        vendor="Acme Pty Ltd",
        field_confidence={"vendor": 0.95},
        field_citations={"vendor": FieldCitation(snippet="Not In OCR")},
    )
    updated, verifications = verify_and_apply_citations(llm, ocr, field_keys=["vendor"])
    assert updated.field_confidence["vendor"] <= 0.5
    detail = citation_audit_detail(verifications)
    assert detail["citation_failed"]
