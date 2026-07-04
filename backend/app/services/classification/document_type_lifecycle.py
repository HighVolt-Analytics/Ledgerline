"""Remove document types from tenant rule book catalogues (SaaS lifecycle)."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import RuleBookConfigPayload


def normalize_document_type_code(code: str | None) -> str:
    return (code or "").strip().upper()


def _catalogue_codes(document_types: list[DocumentTypeDefinition]) -> set[str]:
    return {normalize_document_type_code(dt.code) for dt in document_types if dt.code.strip()}


def scrub_document_type_references(payload: RuleBookConfigPayload) -> RuleBookConfigPayload:
    """Drop bundle / unclassified references to document types no longer in the catalogue."""
    codes = _catalogue_codes(list(payload.document_types))
    if not codes:
        unclassified = payload.document_classification.model_copy(
            update={"unclassified_document_type_code": ""}
        )
        return payload.model_copy(update={"document_classification": unclassified})

    updated_types: list[DocumentTypeDefinition] = []
    for definition in payload.document_types:
        mandatory = [
            code
            for code in definition.bundle_mandatory
            if normalize_document_type_code(code) in codes
        ]
        conditional: list[str] = []
        for item in definition.bundle_conditional:
            token = item.strip()
            if not token:
                continue
            normalized = normalize_document_type_code(token)
            if normalized.startswith("DT-") and normalized not in codes:
                continue
            conditional.append(item)
        if mandatory != definition.bundle_mandatory or conditional != definition.bundle_conditional:
            definition = definition.model_copy(
                update={
                    "bundle_mandatory": mandatory,
                    "bundle_conditional": conditional,
                }
            )
        updated_types.append(definition)

    unclassified_code = normalize_document_type_code(
        payload.document_classification.unclassified_document_type_code
    )
    classification = payload.document_classification
    if unclassified_code and unclassified_code not in codes:
        classification = classification.model_copy(
            update={"unclassified_document_type_code": ""}
        )

    if (
        updated_types == list(payload.document_types)
        and classification == payload.document_classification
    ):
        return payload
    return payload.model_copy(
        update={
            "document_types": updated_types,
            "document_classification": classification,
        }
    )


def remove_document_type_from_payload(
    payload: RuleBookConfigPayload,
    code: str,
) -> RuleBookConfigPayload:
    """Remove one document type and scrub dangling references across the rule book."""
    token = normalize_document_type_code(code)
    if not token:
        raise ValueError("document type code is required")

    remaining = [
        dt
        for dt in payload.document_types
        if normalize_document_type_code(dt.code) != token
    ]
    if len(remaining) == len(payload.document_types):
        raise LookupError(f"Document type {token} is not in this organisation catalogue")

    trimmed = payload.model_copy(update={"document_types": remaining})
    return scrub_document_type_references(trimmed)
