"""Tests for document type recognition migration."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_recognition_migration import (
    migrate_document_type_recognition_row,
    sync_classifier_from_recognition,
)


def test_migrate_legacy_one_line_to_prompt_mode() -> None:
    row = migrate_document_type_recognition_row(
        {
            "code": "DT-01",
            "title": "Invoice",
            "shortTitle": "Invoice",
            "klass": "Transactional",
            "posting": "Yes",
            "oneLine": "Vendor tax invoice with PO reference",
            "routeTarget": "Purchase Management",
        }
    )
    assert row["recognition_mode"] == "prompt"
    assert "Vendor tax invoice" in row["llm_prompt"]
    assert "oneLine" not in row


def test_sync_signals_compiles_classifier() -> None:
    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "Invoice",
            "shortTitle": "Invoice",
            "klass": "Transactional",
            "posting": "Yes",
            "recognition_mode": "signals",
            "recognition_signals": ["heading_invoice"],
            "routeTarget": "Purchase Management",
        }
    )
    synced = sync_classifier_from_recognition(defn)
    assert synced.classifier.enabled is True
    assert synced.classifier.root.get("children")


def test_sync_prompt_disables_classifier() -> None:
    defn = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-02",
            "title": "Permit",
            "shortTitle": "Permit",
            "klass": "Non-transactional",
            "posting": "No",
            "recognition_mode": "prompt",
            "llm_prompt": "Import customs clearance permit letter",
            "routeTarget": "Vault",
        }
    )
    synced = sync_classifier_from_recognition(defn)
    assert synced.classifier.enabled is False
    assert synced.recognition_signals == []
