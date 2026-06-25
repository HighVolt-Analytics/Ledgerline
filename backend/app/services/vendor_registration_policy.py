"""When vendor master registration / hold applies (per route, DT, and VR12)."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_catalog import (
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
    ROUTE_VAULT,
    get_document_type_definition,
)
from app.services.document_type_playbook_profile_service import allows_posting_pipeline
from app.services.document_type_validation_service import (
    PROFILE_NON_ACTIONABLE,
    effective_validation_profile,
)
from app.services.validation_rule_catalog import effective_validation_rules, enabled_rule_codes

_PAYABLE_ROUTES = frozenset({ROUTE_PURCHASE, ROUTE_EXPENSES})
_EXEMPT_ROUTES = frozenset({ROUTE_TEAM, ROUTE_VAULT})
_SUPPORTING_PURCHASE_DOCS = frozenset({"po", "grn"})


def resolve_document_type_definition(
    document_type_code: str | None,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> DocumentTypeDefinition | None:
    code = (document_type_code or "").strip().upper()
    if not code or not document_types:
        return None
    return get_document_type_definition(code, document_types=document_types)


def vendor_master_check_enabled(definition: DocumentTypeDefinition) -> bool:
    """True when VR12 is enabled on this document type's validation profile."""
    profile = effective_validation_profile(definition)
    if profile == PROFILE_NON_ACTIONABLE:
        return False
    rules = effective_validation_rules(definition)
    return "VR12" in enabled_rule_codes(rules)


def vendor_registration_required(
    *,
    route_target: str | None,
    document_type: DocumentTypeDefinition | None = None,
    purchase_document_type: str | None = None,
) -> bool:
    """
    Whether unknown vendors should trigger pending_vendor / registration hold.

    Driven by route, purchase doc role, posting playbook, and per-DT VR12 toggle —
    not hardcoded document-type codes.
    """
    if (purchase_document_type or "").strip().lower() in _SUPPORTING_PURCHASE_DOCS:
        return False

    route = (route_target or "").strip()
    if route in _EXEMPT_ROUTES:
        return False

    if document_type is not None:
        if not document_type.enabled:
            return False
        if not allows_posting_pipeline(document_type):
            return False
        if not vendor_master_check_enabled(document_type):
            return False
        return route in _PAYABLE_ROUTES

    return route in _PAYABLE_ROUTES
