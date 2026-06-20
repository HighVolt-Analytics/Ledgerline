"""Per document-type validation profiles (VR rule sets)."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_catalog import get_document_type_definition
from app.services.document_type_field_defaults import default_validation_profile

ValidationProfile = str

PROFILE_STANDARD = "standard"
PROFILE_DIRECT_EXPENSE = "direct_expense"
PROFILE_NON_ACTIONABLE = "non_actionable"


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
    org_id: int | None = None,
) -> ValidationProfile:
    code = (document_type_code or "").strip().upper()
    if not code:
        return PROFILE_STANDARD
    definition = get_document_type_definition(
        code,
        document_types=document_types,
        org_id=org_id,
    )
    if definition is None:
        seeded = default_validation_profile(code)
        return seeded or PROFILE_STANDARD
    return effective_validation_profile(definition)
