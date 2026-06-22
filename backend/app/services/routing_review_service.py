"""Review gates after document-type classification and GL mapping."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_catalog import get_document_type_definition
from app.services.document_type_classifier import DocumentTypeClassification
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_playbook_profile_service import should_enforce_bundle_mandatory
from app.services.document_type_playbook_service import PlaybookGateResult
from app.services.rule_book_mapper import FALLBACK_RULE_TYPE, MappingDetail


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
        return True
    return (definition.posting or "").strip().lower() == "yes"


def routing_target_missing(invoice: Invoice) -> bool:
    return not (invoice.route_target or "").strip()


def classification_unmatched(classification: DocumentTypeClassification) -> bool:
    return "no classifier matched" in (classification.reason or "").lower()


def requires_playbook_review(
    playbook: PlaybookGateResult | None,
    *,
    definition: DocumentTypeDefinition | None = None,
) -> bool:
    if playbook is None or not playbook.blocks_posting:
        return False
    if definition is not None and not should_enforce_bundle_mandatory(definition):
        return False
    return True


def requires_routing_review(
    invoice: Invoice,
    classification: DocumentTypeClassification,
    *,
    playbook: PlaybookGateResult | None = None,
    definition: DocumentTypeDefinition | None = None,
) -> bool:
    if requires_playbook_review(playbook, definition=definition):
        return True
    if classification_unmatched(classification):
        return True
    if classification.needs_review:
        return True
    return routing_target_missing(invoice)


def requires_gl_mapping_review(
    invoice: Invoice,
    mapping_detail: MappingDetail,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
) -> bool:
    if mapping_detail.rule_type != FALLBACK_RULE_TYPE:
        return False
    return is_posting_document_type(
        invoice.document_type_code,
        document_types=document_types,
        tenant_id=invoice.tenant_id,
    )
