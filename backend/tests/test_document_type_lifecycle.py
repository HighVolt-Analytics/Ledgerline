"""Document type delete and reference scrubbing."""

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.rule_book_config import DocumentClassificationConfig, RuleBookConfigPayload
from app.services.document_type_lifecycle import (
    remove_document_type_from_payload,
    scrub_document_type_references,
)


def _type(code: str, **kwargs) -> DocumentTypeDefinition:
    base = dict(
        code=code,
        title=code,
        shortTitle=code,
        klass="Transactional",
        posting="Yes",
        fraudRisk="low",
        oneLine="test",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(enabled=False, priority=100, confidence=0.85),
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_remove_document_type_drops_row() -> None:
    payload = RuleBookConfigPayload(
        document_types=[_type("DT-01"), _type("DT-99", title="Custom")],
    )
    updated = remove_document_type_from_payload(payload, "dt-99")
    codes = {row.code for row in updated.document_types}
    assert codes == {"DT-01"}


def test_remove_document_type_scrubs_bundle_mandatory() -> None:
    payload = RuleBookConfigPayload(
        document_types=[
            _type("DT-01", bundle_mandatory=["DT-99"]),
            _type("DT-99"),
        ],
    )
    updated = remove_document_type_from_payload(payload, "DT-99")
    assert updated.document_types[0].bundle_mandatory == []


def test_remove_document_type_clears_unclassified_pointer() -> None:
    payload = RuleBookConfigPayload(
        document_types=[_type("DT-01")],
        document_classification=DocumentClassificationConfig(
            unclassified_document_type_code="DT-99",
        ),
    )
    updated = scrub_document_type_references(payload)
    assert updated.document_classification.unclassified_document_type_code == ""


def test_remove_missing_document_type_raises() -> None:
    payload = RuleBookConfigPayload(document_types=[_type("DT-01")])
    try:
        remove_document_type_from_payload(payload, "DT-77")
    except LookupError as exc:
        assert "DT-77" in str(exc)
    else:
        raise AssertionError("expected LookupError")
