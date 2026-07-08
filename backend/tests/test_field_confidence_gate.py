"""Field confidence gate presence checks."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.rule_book_config import AiClassificationConfig
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_pipeline_phases import (
    evaluate_field_confidence_gate,
    field_confidence_audit_detail,
)


def _dt_definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-12",
        title="Expense claim",
        shortTitle="Expense",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=[],
        llm_prompt="",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(),
        extractionFields=["vendor", "total", "invoice_no"],
        requiredFields=["vendor", "total"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_missing_total_fails_gate() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-12",
        confidence=0.95,
        vendor="Acme",
        invoice_no="INV-1",
        field_confidence={"vendor": 0.95, "invoice_no": 0.95, "total": 0.0},
    )
    parsed = InvoiceData(vendor="Acme", invoice_no="INV-1", document_text="Vendor: Acme")
    invoice = Invoice(vendor="Acme", invoice_no="INV-1")
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
        dt_definition=_dt_definition(),
        parsed=parsed,
        invoice=invoice,
        confirmed_dt="DT-12",
    )
    assert result.passed is False
    assert "total" in result.missing_gate_fields
    detail = field_confidence_audit_detail(result)
    assert detail["missing_gate_fields"] == ["total"]
    assert detail["compare_passed"] is False


def test_present_total_passes_gate() -> None:
    from decimal import Decimal

    llm = LlmDocumentResult(
        suggested_dt="DT-12",
        confidence=0.95,
        vendor="Acme",
        total=Decimal("100.00"),
        field_confidence={"vendor": 0.95, "total": 0.95},
    )
    parsed = InvoiceData(vendor="Acme", total=Decimal("100.00"), document_text="Total 100.00")
    invoice = Invoice(vendor="Acme")
    invoice.total = Decimal("100.00")
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
        dt_definition=_dt_definition(),
        parsed=parsed,
        invoice=invoice,
        confirmed_dt="DT-12",
    )
    assert result.passed is True
    assert result.missing_gate_fields == []


def test_di_line_items_not_flagged_when_present_with_empty_llm_field_confidence() -> None:
    from app.services.invoice.invoice_data import ParsedLineItem

    llm = LlmDocumentResult(
        suggested_dt="DT-12",
        confidence=0.95,
        vendor="Acme",
        total=Decimal("100.00"),
        field_confidence={},
    )
    parsed = InvoiceData(
        vendor="Acme",
        total=Decimal("100.00"),
        line_items=[ParsedLineItem(description="Widget", amount=Decimal("50.00"))],
        document_text="Widget 50.00 Total 100.00",
    )
    invoice = Invoice(vendor="Acme")
    invoice.total = Decimal("100.00")
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
        dt_definition=_dt_definition(
            extractionFields=["vendor", "total", "line_items"],
            requiredFields=["vendor", "total", "line_items"],
        ),
        parsed=parsed,
        invoice=invoice,
        confirmed_dt="DT-12",
    )
    assert result.passed is True
    assert "line_items" not in result.missing_gate_fields
    assert "line_items" in result.skipped_fields_present_after_merge
