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


def test_employee_claim_recommends_claimant_and_total() -> None:
    warnings = audit_document_type_extraction_config(
        _definition(
            code="DT-08",
            title="Expense claim",
            shortTitle="Expense claim",
            playbook_profile="employee_claim",
            routeTarget="Team Expenses",
            extraction_fields=["total", "invoice_date"],
        )
    )
    joined = " ".join(warnings)
    assert "email_sender" in joined or "invoice_no" in joined or "employee_name" in joined


def test_log_warnings_dedupes_identical_sets(caplog) -> None:
    import logging

    from app.services.rule_book import extraction_field_config_audit as audit_mod

    audit_mod._LOGGED_WARNING_FINGERPRINTS.clear()
    payload = RuleBookConfigPayload(
        document_types=[
            _definition(extraction_fields=["invoice_no", "so_reference", "line_items"]),
        ]
    )
    with caplog.at_level(logging.WARNING):
        assert audit_mod.log_extraction_field_config_warnings(payload) >= 1
        first = sum(1 for r in caplog.records if r.msg == "extraction_field_config_gap")
        assert audit_mod.log_extraction_field_config_warnings(payload) >= 1
        second = sum(1 for r in caplog.records if r.msg == "extraction_field_config_gap")
    assert second == first


def test_backfill_unions_recommended_into_existing_extraction_fields() -> None:
    from app.schemas.rule_book_config import _backfill_extraction_fields_from_shipped_defaults

    data = {
        "document_types": [
            {
                "code": "DT-08",
                "title": "Expense claim",
                "shortTitle": "Expense claim",
                "klass": "Transactional",
                "posting": "Yes",
                "recognitionMode": "signals",
                "recognitionSignals": [],
                "llmPrompt": "",
                "routeTarget": "Team Expenses",
                "playbookProfile": "employee_claim",
                "extractionFields": ["total", "invoice_date"],
            }
        ]
    }
    out = _backfill_extraction_fields_from_shipped_defaults(data)
    keys = {
        str(k).strip().lower()
        for k in (out["document_types"][0].get("extraction_fields") or [])
    }
    assert "total" in keys
    assert "invoice_date" in keys
    assert "invoice_no" in keys
    assert "email_sender" in keys


def test_audit_rule_book_iterates_enabled_types() -> None:
    payload = RuleBookConfigPayload(
        document_types=[
            _definition(),
            _definition(code="DT-14", enabled=False),
        ]
    )
    warnings = audit_rule_book_extraction_config(payload)
    assert len(warnings) == 1
