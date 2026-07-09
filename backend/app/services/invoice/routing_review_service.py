"""Review gates after LLM + policy document-type classification."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.classification_decision import ClassificationDecision
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_classifier import DocumentTypeClassification
from app.services.classification.document_type_playbook_service import PlaybookGateResult
from app.services.rule_book.rule_book_mapper import FALLBACK_RULE_TYPE, MappingDetail


def is_posting_document_type(
    code: str | None,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
) -> bool:
    normalized = (code or "").strip().upper()
    if not normalized:
        return True
    definition = get_document_type_definition(
        normalized,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    if definition is None:
        return False
    return (definition.posting or "").strip().lower() == "yes"


def routing_target_missing(invoice: Invoice) -> bool:
    return not (invoice.route_target or "").strip()


def classification_unmatched(classification: DocumentTypeClassification) -> bool:
    return not (classification.code or "").strip()


def requires_classification_review_v2(decision: ClassificationDecision) -> bool:
    """Block downstream pipeline until LLM + policy classification passes."""
    return not decision.auto_eligible


def requires_classification_review(
    invoice: Invoice,
    classification: DocumentTypeClassification,
) -> bool:
    """Legacy gate — prefer requires_classification_review_v2 for LLM pipeline."""
    if classification_unmatched(classification):
        return True
    if classification.needs_review:
        return True
    return routing_target_missing(invoice)


def requires_playbook_review(
    playbook: PlaybookGateResult | None,
    *,
    definition: DocumentTypeDefinition | None = None,
) -> bool:
    """Field and bundle gaps are enforced via VR03 / VR-PB02 at validation, not here."""
    _ = (playbook, definition)
    return False


def requires_routing_review(
    invoice: Invoice,
    classification: DocumentTypeClassification,
    *,
    playbook: PlaybookGateResult | None = None,
    definition: DocumentTypeDefinition | None = None,
    decision: ClassificationDecision | None = None,
) -> bool:
    if decision is not None and requires_classification_review_v2(decision):
        return True
    if requires_playbook_review(playbook, definition=definition):
        return True
    return requires_classification_review(invoice, classification)


def requires_gl_mapping_review(
    invoice: Invoice,
    mapping_detail: MappingDetail,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
) -> bool:
    if mapping_detail.rule_type != FALLBACK_RULE_TYPE:
        return False
    return is_posting_document_type(
        invoice.document_type_code,
        document_types=document_types,
        tenant_id=tenant_id,
    )
