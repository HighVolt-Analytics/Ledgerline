"""Per document-type validation profiles (VR rule sets)."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_field_defaults import default_validation_profile

ValidationProfile = str

PROFILE_STANDARD = "standard"
PROFILE_DIRECT_EXPENSE = "direct_expense"
PROFILE_NON_ACTIONABLE = "non_actionable"

_SUPPORTING_PURCHASE_DOCS = frozenset({"po", "grn"})


def effective_validation_profile(definition: DocumentTypeDefinition) -> ValidationProfile:
    if definition.validation_profile:
        return definition.validation_profile
    seeded = default_validation_profile(definition.code)
    if seeded:
        return seeded
    return PROFILE_STANDARD


def resolve_validation_profile(
    document_type_code: str | None,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
) -> ValidationProfile:
    code = (document_type_code or "").strip().upper()
    if not code:
        return PROFILE_STANDARD
    definition = get_document_type_definition(
        code,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    if definition is None:
        seeded = default_validation_profile(code)
        return seeded or PROFILE_STANDARD
    return effective_validation_profile(definition)


def validation_pass_applicable(
    *,
    route_target: str | None,
    document_type: DocumentTypeDefinition | None = None,
    purchase_document_type: str | None = None,
) -> bool:
    """Whether inbox VR pass % is meaningful for this document."""
    from app.services.classification.document_type_playbook_profile_service import allows_posting_pipeline
    from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM, ROUTE_VAULT

    if (purchase_document_type or "").strip().lower() in _SUPPORTING_PURCHASE_DOCS:
        return False

    route = (route_target or "").strip()
    if route in {ROUTE_TEAM, ROUTE_VAULT}:
        return False

    if document_type is not None:
        if effective_validation_profile(document_type) == PROFILE_NON_ACTIONABLE:
            return False
        if not allows_posting_pipeline(document_type):
            return False

    return True


def display_validation_pass_percent(
    validation_results: list[object] | None,
    *,
    applicable: bool,
) -> int | None:
    """Compute inbox VR pass % — null when validation scoring does not apply."""
    if not applicable or not validation_results:
        return None
    evaluated = [row for row in validation_results if not getattr(row, "skipped", False)]
    if not evaluated:
        return None
    passed = sum(1 for row in evaluated if getattr(row, "passed", False))
    return round(100 * passed / len(evaluated))
