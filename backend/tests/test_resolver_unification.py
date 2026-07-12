"""Resolver unification backward-compat tests."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_playbook_profile_service import effective_playbook_profile
from app.services.extraction.extraction_field_values import configured_extraction_keys


def _dt01_definition() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "PO-based goods invoice",
            "shortTitle": "PO goods invoice",
            "klass": "Transactional",
            "posting": "Yes",
            "recognitionMode": "signals",
            "routeTarget": "Purchase Management",
            "enabled": True,
        }
    )


def test_non_repurposed_dt01_extraction_keys_unchanged() -> None:
    defn = _dt01_definition()
    keys = configured_extraction_keys(defn)
    assert "vendor" in keys
    assert "invoice_no" in keys
    assert "line_items" in keys


def test_non_repurposed_dt01_playbook_profile_unchanged() -> None:
    defn = _dt01_definition()
    assert effective_playbook_profile(defn) == "po_goods"


def test_repurposed_dt13_empty_playbook_profile() -> None:
    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-13",
            "title": "PACKING LIST",
            "shortTitle": "PACKING LIST",
            "klass": "Non-transactional",
            "posting": "No",
            "recognitionMode": "prompt",
            "routeTarget": "Vault",
            "enabled": True,
        }
    )
    assert effective_playbook_profile(defn) == ""


def test_repurposed_dt13_does_not_inherit_shipped_extraction_defaults() -> None:
    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-13",
            "title": "PACKING LIST",
            "shortTitle": "PACKING LIST",
            "klass": "Non-transactional",
            "posting": "No",
            "recognitionMode": "prompt",
            "routeTarget": "Vault",
            "enabled": True,
            "extractionFields": ["invoice_no", "so_reference", "line_items"],
        }
    )
    keys = configured_extraction_keys(defn)
    assert keys == ["invoice_no", "so_reference", "line_items"]


def test_repurposed_packing_list_empty_fields_stays_empty() -> None:
    """Repurposed non-transactional DT does not inherit invoice field defaults."""
    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-13",
            "title": "PACKING LIST",
            "shortTitle": "PACKING LIST",
            "klass": "Non-transactional",
            "posting": "No",
            "recognitionMode": "prompt",
            "routeTarget": "Vault",
            "enabled": True,
            "extractionFields": [],
        }
    )
    assert configured_extraction_keys(defn) == []
