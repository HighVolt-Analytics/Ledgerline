"""Self-consistency comparison tests."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.services.extraction.self_consistency_service import (
    apply_self_consistency_outcomes,
    compare_self_consistency,
    posting_critical_keys_for_dt,
)


def test_three_way_agreement_passes() -> None:
    base = LlmDocumentResult(invoice_no="INV-1", total="100")
    retries = [
        LlmDocumentResult(invoice_no="INV-1", total="100"),
        LlmDocumentResult(invoice_no="INV-1", total="100"),
    ]
    outcomes = compare_self_consistency(base, retries, ["invoice_no", "total"])
    assert outcomes["invoice_no"]["agreed"] is True
    assert outcomes["total"]["agreed"] is True


def test_disagreement_flags_review() -> None:
    base = LlmDocumentResult(total="100")
    retries = [
        LlmDocumentResult(total="200"),
        LlmDocumentResult(total="300"),
    ]
    outcomes = compare_self_consistency(base, retries, ["total"])
    assert outcomes["total"]["agreed"] is False
    updated = apply_self_consistency_outcomes(
        LlmDocumentResult(total="100", field_confidence={"total": 0.9}),
        outcomes,
    )
    assert updated.field_confidence["total"] <= 0.4


def test_posting_critical_keys_intersection() -> None:
    dt = DocumentTypeDefinition(
        code="DT-01",
        title="Test",
        shortTitle="Test",
        klass="Transactional",
        posting="Yes",
        required_fields=["vendor", "invoice_no", "total", "due_date", "po_reference"],
        extraction_fields=["vendor", "invoice_no", "total", "due_date", "po_reference"],
    )
    keys = posting_critical_keys_for_dt(dt)
    assert "total" in keys
    assert "vendor" in keys
