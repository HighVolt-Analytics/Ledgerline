"""Document type catalog metadata tests."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import (
    classification_hints_for_dt,
    cross_field_rules_for_dt,
    get_dt_catalog_entry,
)
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows


def test_dt_catalog_entry_without_org_definition_is_empty() -> None:
    entry = get_dt_catalog_entry("DT-01")
    assert entry.code == "DT-01"
    assert entry.classification_hints == ()
    assert entry.azure_di_profile == ""


def test_classification_hints_helpers_use_org_titles() -> None:
    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "Vendor tax invoice",
            "shortTitle": "Tax invoice",
            "klass": "Transactional",
            "posting": "Yes",
            "routeTarget": "Purchase Management",
            "enabled": True,
        }
    )
    positive, negative = classification_hints_for_dt("DT-01", dt_definition=defn)
    assert positive == ["Vendor tax invoice", "Tax invoice"]
    assert negative == []


def test_cross_field_rules_are_org_only() -> None:
    rules = cross_field_rules_for_dt("DT-01")
    assert rules == []


def test_org_repurposed_dt_does_not_inherit_shipped_reconciliation_profile() -> None:
    from app.services.classification.document_type_catalog import playbook_profile_for_dt
    from app.services.extraction.extraction_orchestrator import should_run_prebuilt_invoice_di

    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-13",
            "title": "PACKING LIST",
            "shortTitle": "PACKING LIST",
            "klass": "Non-transactional",
            "posting": "No",
            "recognitionMode": "prompt",
            "llmPrompt": "Packing list with qty columns, no pricing.",
            "routeTarget": "Vault",
            "enabled": True,
        }
    )
    assert playbook_profile_for_dt(defn) == ""
    assert should_run_prebuilt_invoice_di("DT-13", defn) is False


def test_org_repurposed_dt_uses_org_hints_not_shipped_template() -> None:
    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-13",
            "title": "PACKING LIST",
            "shortTitle": "PACKING LIST",
            "klass": "Non-transactional",
            "posting": "No",
            "recognitionMode": "prompt",
            "llmPrompt": "Packing list with qty columns, no pricing.",
            "routeTarget": "Vault",
            "enabled": True,
        }
    )
    entry = get_dt_catalog_entry("DT-13", dt_definition=defn)
    assert entry.classification_hints == ("PACKING LIST",)
    assert "Vendor statement" not in entry.classification_hints

    rows = build_llm_catalogue_rows([defn])
    assert rows[0]["classification_hints"] == ["PACKING LIST"]
    assert "Vendor statement" not in rows[0].get("classification_hints", [])
