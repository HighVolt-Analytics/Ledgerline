"""Extraction field config audit warnings."""

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.services.rule_book.extraction_field_config_audit import (
    audit_document_type_extraction_config,
    audit_rule_book_extraction_config,
)
from app.schemas.rule_book_config import RuleBookConfigPayload


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-13",
        title="Packing List",
        shortTitle="PACKING LIST",
        klass="Non-transactional",
        posting="No",
        recognition_mode="signals",
        recognition_signals=[],
        llm_prompt="",
        routeTarget="Sales Management",
        classifier=DocumentTypeClassifier(),
        playbook_profile="ar_goods_2way",
        extraction_fields=["invoice_no", "so_reference", "line_items"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_audit_warns_missing_invoice_date_for_ar_goods_2way() -> None:
    warnings = audit_document_type_extraction_config(_definition())
    assert any("invoice_date" in message for message in warnings)


def test_audit_silent_for_supporting_profile() -> None:
    warnings = audit_document_type_extraction_config(
        _definition(playbook_profile="supporting", extraction_fields=["attachment_name"])
    )
    assert warnings == []


def test_audit_rule_book_iterates_enabled_types() -> None:
    payload = RuleBookConfigPayload(
        document_types=[
            _definition(),
            _definition(code="DT-14", enabled=False),
        ]
    )
    warnings = audit_rule_book_extraction_config(payload)
    assert len(warnings) == 1
