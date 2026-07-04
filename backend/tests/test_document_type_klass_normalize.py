"""Document type klass collapse — two values only."""

from __future__ import annotations

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_klass import (
    KLASS_NON_TRANSACTIONAL,
    KLASS_TRANSACTIONAL,
    derive_posting_from_klass_and_profile,
    is_trans_posting,
    normalize_document_type_klass,
)
from app.services.classification.document_type_playbook_profile_service import (
    allows_posting_pipeline,
    gl_posting_applicable_for_invoice,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Transactional", KLASS_TRANSACTIONAL),
        ("Pre-transactional", KLASS_TRANSACTIONAL),
        ("Supporting", KLASS_NON_TRANSACTIONAL),
        ("Reconciliation", KLASS_NON_TRANSACTIONAL),
        ("Informational", KLASS_NON_TRANSACTIONAL),
        ("Master-data", KLASS_NON_TRANSACTIONAL),
        ("Non-actionable", KLASS_NON_TRANSACTIONAL),
        ("Compliance", KLASS_NON_TRANSACTIONAL),
        ("Trans-posting", KLASS_TRANSACTIONAL),
        ("Non-trans, non-posting", KLASS_NON_TRANSACTIONAL),
        ("Non-transactional", KLASS_NON_TRANSACTIONAL),
        (KLASS_TRANSACTIONAL, KLASS_TRANSACTIONAL),
        (KLASS_NON_TRANSACTIONAL, KLASS_NON_TRANSACTIONAL),
    ],
)
def test_normalize_document_type_klass(raw: str, expected: str) -> None:
    assert normalize_document_type_klass(raw) == expected


def test_derive_posting_from_klass_and_profile() -> None:
    assert (
        derive_posting_from_klass_and_profile(KLASS_NON_TRANSACTIONAL, "supporting")
        == "No"
    )
    assert (
        derive_posting_from_klass_and_profile(KLASS_TRANSACTIONAL, "po_goods")
        == "Yes"
    )
    assert (
        derive_posting_from_klass_and_profile(
            KLASS_TRANSACTIONAL,
            "pre_transactional",
        )
        == "Down-payment"
    )
    assert (
        derive_posting_from_klass_and_profile(
            KLASS_TRANSACTIONAL,
            "standard_transactional",
            existing_posting="Conditional",
        )
        == "Conditional"
    )


def test_document_type_definition_normalizes_klass_on_validate() -> None:
    definition = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-99",
            "title": "Legacy supporting",
            "shortTitle": "Legacy",
            "klass": "Supporting",
            "posting": "Maybe",
            "oneLine": "Test",
            "playbook_profile": "supporting",
        }
    )
    assert definition.klass == KLASS_NON_TRANSACTIONAL
    assert definition.posting == "No"


def test_allows_posting_pipeline_after_klass_collapse() -> None:
    posting = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "Invoice",
            "shortTitle": "Invoice",
            "klass": KLASS_TRANSACTIONAL,
            "posting": "Yes",
            "oneLine": "Posts",
            "playbook_profile": "po_goods",
        }
    )
    non_posting = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-02",
            "title": "PO copy",
            "shortTitle": "PO",
            "klass": KLASS_NON_TRANSACTIONAL,
            "posting": "No",
            "oneLine": "Supporting",
            "playbook_profile": "supporting",
            "purchase_bundle_role": "po",
        }
    )
    assert allows_posting_pipeline(posting) is True
    assert allows_posting_pipeline(non_posting) is False
    assert is_trans_posting(posting) is True
    assert is_trans_posting(non_posting) is False


def test_gl_posting_not_applicable_for_non_trans_klass() -> None:
    from types import SimpleNamespace

    inv = SimpleNamespace(
        purchase_document_type="",
        sales_document_type="",
        route_target="Purchase Management",
        document_type_code="DT-02",
    )
    definition = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-02",
            "title": "PO copy",
            "shortTitle": "PO",
            "klass": KLASS_NON_TRANSACTIONAL,
            "posting": "No",
            "oneLine": "Supporting",
            "playbook_profile": "supporting",
        }
    )
    assert gl_posting_applicable_for_invoice(inv, document_type=definition) is False
