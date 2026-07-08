"""Route-level compulsory extraction field baselines — mirrors frontend documentExtractionFields.ts."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition, DocumentTypeRouteTarget
from app.services.classification.document_type_field_keys import (
    INFRASTRUCTURE_EXTRACTION_FIELD_KEYS,
    normalize_extraction_field_keys,
)

_ROUTE_COMPULSORY_BASELINE: dict[DocumentTypeRouteTarget, tuple[str, ...]] = {
    "Purchase Management": ("vendor", "subtotal", "gst", "total", "due_date"),
    "Expenses Management": ("vendor", "subtotal", "gst", "total", "due_date"),
    "Sales Management": ("vendor", "subtotal", "gst", "total", "due_date"),
    "Team Expenses": ("subtotal", "gst", "total"),
    "Vault": (),
}

_NON_TRANSACTIONAL_PLAYBOOK_PROFILES = frozenset(
    {
        "supporting",
        "non_actionable",
        "informational",
        "reconciliation",
        "master_data",
        "compliance_route",
    }
)


def route_compulsory_baseline(route_target: str | None) -> list[str]:
    token = (route_target or "").strip()
    if token not in _ROUTE_COMPULSORY_BASELINE:
        return []
    return list(_ROUTE_COMPULSORY_BASELINE[token])  # type: ignore[index]


def is_transactional_for_route_compulsory(definition: DocumentTypeDefinition) -> bool:
    if (definition.posting or "").strip() == "No":
        return False
    profile = (definition.playbook_profile or "").strip().lower()
    if profile in _NON_TRANSACTIONAL_PLAYBOOK_PROFILES:
        return False
    return True


def _normalize_compulsory_fields(required: list[str], extraction: list[str]) -> list[str]:
    ext_set = set(extraction)
    req = [
        key
        for key in normalize_extraction_field_keys(required)
        if key not in INFRASTRUCTURE_EXTRACTION_FIELD_KEYS
    ]
    return [key for key in req if key in ext_set]


def _ensure_extraction_superset(required: list[str], extraction: list[str]) -> list[str]:
    out = normalize_extraction_field_keys(extraction)
    seen = set(out)
    for key in normalize_extraction_field_keys(required):
        if key not in seen:
            out.append(key)
            seen.add(key)
    return out


def merge_route_compulsory_into_document_type(
    definition: DocumentTypeDefinition,
) -> DocumentTypeDefinition:
    extraction_base = normalize_extraction_field_keys(list(definition.extraction_fields or []))
    if not is_transactional_for_route_compulsory(definition):
        required_fields = _normalize_compulsory_fields(
            list(definition.required_fields or []),
            extraction_base,
        )
        return definition.model_copy(
            update={
                "required_fields": required_fields,
                "extraction_fields": _ensure_extraction_superset(required_fields, extraction_base),
            }
        )

    baseline = route_compulsory_baseline(definition.route_target)
    merged_required = normalize_extraction_field_keys(
        list(definition.required_fields or []) + baseline
    )
    extraction_fields = _ensure_extraction_superset(merged_required, extraction_base)
    required_fields = _normalize_compulsory_fields(merged_required, extraction_fields)
    return definition.model_copy(
        update={
            "required_fields": required_fields,
            "extraction_fields": extraction_fields,
        }
    )


def merge_route_compulsory_into_config(
    document_types: list[DocumentTypeDefinition],
) -> list[DocumentTypeDefinition]:
    return [merge_route_compulsory_into_document_type(defn) for defn in document_types]
