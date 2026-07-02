"""Resolve effective playbook profile, match, and approval policies per document type."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.playbook_policy import ApprovalPolicy, MatchPolicy, PlaybookProfile
from app.services.playbook_profile_catalog import (
    PlaybookProfilePreset,
    preset_for_profile,
)


def effective_playbook_profile(definition: DocumentTypeDefinition) -> PlaybookProfile:
    explicit = (definition.playbook_profile or "").strip().lower()
    if explicit:
        return explicit  # type: ignore[return-value]
    return "standard_transactional"


def _preset(definition: DocumentTypeDefinition) -> PlaybookProfilePreset:
    return preset_for_profile(effective_playbook_profile(definition))


def effective_match_policy(definition: DocumentTypeDefinition) -> MatchPolicy:
    if definition.match_policy is not None:
        return definition.match_policy
    return MatchPolicy(mode=_preset(definition).match_mode)


def effective_approval_policy(definition: DocumentTypeDefinition) -> ApprovalPolicy:
    if definition.approval_policy is not None:
        return definition.approval_policy
    return ApprovalPolicy(mode=_preset(definition).approval_mode)


def should_enforce_bundle_mandatory(definition: DocumentTypeDefinition) -> bool:
    return _preset(definition).enforce_bundle_mandatory


def match_mode_requires_po(match_mode: str) -> bool:
    return match_mode in {"three_way_po_grn", "two_way_po_ses"}


def allows_posting_pipeline(definition: DocumentTypeDefinition) -> bool:
    mode = effective_approval_policy(definition).mode
    if mode == "no_posting":
        return False
    posting = (definition.posting or "").strip().lower()
    return posting in {"yes", "conditional", "down-payment"}


def clear_invoice_gl_mapping(invoice) -> None:
    """Remove GL mapping from documents that never post to the ledger."""
    invoice.account_code = None
    invoice.account_name = None


def gl_posting_applicable_for_invoice(
    invoice,
    *,
    document_type: DocumentTypeDefinition | None = None,
    document_types: list[DocumentTypeDefinition] | None = None,
) -> bool:
    """True when this document should map/post GL entries (finance control)."""
    from app.services.invoice_evaluation_service import ROUTE_VAULT

    purchase_role = (getattr(invoice, "purchase_document_type", None) or "").strip().lower()
    if purchase_role in {"po", "grn"}:
        return False

    sales_role = (getattr(invoice, "sales_document_type", None) or "").strip().lower()
    if sales_role in {"so", "dn"}:
        return False

    if (getattr(invoice, "route_target", None) or "").strip() == ROUTE_VAULT:
        return False

    if document_type is None and document_types is not None:
        from app.services.document_type_catalog import get_document_type_definition

        code = (getattr(invoice, "document_type_code", None) or "").strip().upper()
        if code:
            document_type = get_document_type_definition(code, document_types=document_types)

    if document_type is not None:
        return allows_posting_pipeline(document_type)

    return True


def playbook_policy_audit_detail(definition: DocumentTypeDefinition) -> dict[str, object]:
    profile = effective_playbook_profile(definition)
    match_policy = effective_match_policy(definition)
    approval_policy = effective_approval_policy(definition)
    return {
        "playbook_profile": profile,
        "match_mode": match_policy.mode,
        "approval_mode": approval_policy.mode,
        "enforce_bundle_mandatory": should_enforce_bundle_mandatory(definition),
        "allows_posting_pipeline": allows_posting_pipeline(definition),
    }
