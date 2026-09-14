"""Load DT-xx catalogue from org rule book config."""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.registry.dt_catalog_entry import DtCatalogEntry
from app.schemas.document_type import DocumentTypeDefinition

ROUTE_PURCHASE = "Purchase Management"
ROUTE_SALES = "Sales Management"
ROUTE_EXPENSES = "Expenses Management"
ROUTE_TEAM = "Team Expenses"
ROUTE_VAULT = "Vault"

DEFAULT_DOCUMENT_TYPE_ROUTE_TARGETS: dict[str, str] = {
    "DT-01": ROUTE_PURCHASE,
    "DT-02": ROUTE_PURCHASE,
    "DT-03": ROUTE_PURCHASE,
    "DT-04": ROUTE_PURCHASE,
    "DT-05": ROUTE_PURCHASE,
    "DT-06": ROUTE_VAULT,
    "DT-07": ROUTE_PURCHASE,
    "DT-08": ROUTE_EXPENSES,
    "DT-09": ROUTE_PURCHASE,
    "DT-10": ROUTE_PURCHASE,
    "DT-11": ROUTE_PURCHASE,
    "DT-12": ROUTE_TEAM,
    "DT-13": ROUTE_VAULT,
    "DT-14": ROUTE_PURCHASE,
    "DT-15": ROUTE_PURCHASE,
    "DT-16": ROUTE_PURCHASE,
    "DT-17": ROUTE_PURCHASE,
    "DT-18": ROUTE_VAULT,
    "DT-19": ROUTE_PURCHASE,
    "DT-20": ROUTE_PURCHASE,
    "DT-21": ROUTE_EXPENSES,
    "DT-22": ROUTE_VAULT,
    "DT-23": ROUTE_VAULT,
    "DT-24": ROUTE_VAULT,
    "DT-25": ROUTE_VAULT,
    "DT-26": ROUTE_SALES,
    "DT-27": ROUTE_SALES,
    "DT-28": ROUTE_SALES,
}

DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN = 0.65


def _catalog_path() -> Path:
    return Path(get_settings().document_types_catalog_path)


def _parse_catalog_items(raw: object) -> list[DocumentTypeDefinition]:
    if not isinstance(raw, list):
        raise ValueError("document types catalogue must be a JSON array")
    return [DocumentTypeDefinition.model_validate(item) for item in raw]


def load_shipped_default_document_types() -> list[DocumentTypeDefinition]:
    """Legacy DT-xx shipped catalogue removed — org rule book rows are self-contained."""
    return []


@lru_cache
def load_document_type_catalog(tenant_id: int) -> tuple[DocumentTypeDefinition, ...]:
    """Deprecated: pass document_types from load_config_for_tenant instead."""
    raise RuntimeError(
        "load_document_type_catalog is deprecated; pass document_types from config"
    )


def merge_document_type_definitions(
    tenant_types: Sequence[DocumentTypeDefinition],
) -> list[DocumentTypeDefinition]:
    """Shipped catalogue plus tenant overrides (tenant wins on code conflict)."""
    by_code = {row.code.upper(): row for row in load_shipped_default_document_types()}
    for row in tenant_types:
        by_code[row.code.upper()] = row
    return sorted(by_code.values(), key=lambda row: row.code.upper())


def org_document_types_for_bundle_export(
    tenant_types: Sequence[DocumentTypeDefinition],
) -> list[DocumentTypeDefinition]:
    """Org-configured document types only — excludes shipped template defaults."""
    return sorted(
        [row for row in tenant_types if (row.code or "").strip()],
        key=lambda row: (row.code or "").upper(),
    )


def effective_document_types_for_export(
    tenant_types: Sequence[DocumentTypeDefinition],
    *,
    invoice_codes: set[str] | None = None,
) -> list[DocumentTypeDefinition]:
    """Catalogue for bundle export — full shipped baseline with tenant overrides."""
    merged = merge_document_type_definitions(tenant_types)
    if not invoice_codes:
        return merged
    by_code = {row.code.upper(): row for row in merged}
    shipped = {row.code.upper(): row for row in load_shipped_default_document_types()}
    for code in invoice_codes:
        token = (code or "").strip().upper()
        if token and token not in by_code and token in shipped:
            by_code[token] = shipped[token]
    return sorted(by_code.values(), key=lambda row: row.code.upper())


def get_document_type_definition(
    code: str,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
) -> DocumentTypeDefinition | None:
    del tenant_id
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    catalog = document_types
    if catalog is None:
        return None
    for item in catalog:
        if item.code.upper() == normalized:
            return item
    return None


def min_route_confidence_for_document_type(
    code: str,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    *,
    tenant_id: int | None = None,
) -> float:
    definition = get_document_type_definition(
        code,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    if definition is None:
        return DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN
    return float(definition.min_route_confidence)


def resolved_route_for_definition(
    definition: DocumentTypeDefinition | None,
) -> str | None:
    """Catalogue route for a DT: employee_claim playbook, else route_target, else inference.

    Never keys on a fixed code (e.g. DT-12). Custom tenant DTs with
    ``playbook_profile=employee_claim`` resolve to Team Expenses the same way.
    """
    if definition is None:
        return None
    if not getattr(definition, "enabled", True):
        return None
    playbook = (definition.playbook_profile or "").strip().lower()
    if playbook == "employee_claim":
        return ROUTE_TEAM
    route = (definition.route_target or "").strip()
    if route:
        return route
    if playbook:
        from app.services.classification.document_type_recognition_signals import (
            infer_document_metadata,
        )

        bundle_role = (getattr(definition, "purchase_bundle_role", None) or "").strip()
        _klass, _posting, inferred = infer_document_metadata(
            playbook, bundle_role=bundle_role
        )
        if (inferred or "").strip():
            return inferred.strip()
    code = (definition.code or "").strip().upper()
    return DEFAULT_DOCUMENT_TYPE_ROUTE_TARGETS.get(code) if code else None


def is_team_expenses_document_type(
    definition: DocumentTypeDefinition | None,
) -> bool:
    """True when the DT is configured for Team Expenses (route or employee_claim playbook)."""
    if definition is None:
        return False
    if (definition.playbook_profile or "").strip().lower() == "employee_claim":
        return True
    return resolved_route_for_definition(definition) == ROUTE_TEAM


def team_expenses_document_types(
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> list[DocumentTypeDefinition]:
    """Enabled catalogue rows that route to Team Expenses (any tenant code)."""
    if not document_types:
        return []
    return [
        dt
        for dt in document_types
        if getattr(dt, "enabled", True) and is_team_expenses_document_type(dt)
    ]


def route_target_for_document_type(
    code: str,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    *,
    tenant_id: int | None = None,
) -> str | None:
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    definition = get_document_type_definition(
        normalized,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    if definition is None:
        return DEFAULT_DOCUMENT_TYPE_ROUTE_TARGETS.get(normalized)
    resolved = resolved_route_for_definition(definition)
    if resolved:
        return resolved
    return DEFAULT_DOCUMENT_TYPE_ROUTE_TARGETS.get(normalized)


def resolve_document_type_for_purchase_kind(
    kind: str | None,
    document_types: Sequence[DocumentTypeDefinition],
) -> DocumentTypeDefinition | None:
    """Map PO / GRN / invoice purchase role to an org catalogue row."""
    from app.models.invoice import PurchaseDocumentType

    normalized = (kind or "").strip().lower()
    if normalized not in {
        PurchaseDocumentType.PO.value,
        PurchaseDocumentType.GRN.value,
        PurchaseDocumentType.INVOICE.value,
    }:
        return None

    bundle_role = {
        PurchaseDocumentType.PO.value: "po",
        PurchaseDocumentType.GRN.value: "grn",
    }.get(normalized)
    if bundle_role:
        for item in document_types:
            if not item.enabled:
                continue
            if (item.purchase_bundle_role or "").strip().lower() == bundle_role:
                return item

    if normalized == PurchaseDocumentType.INVOICE.value:
        from app.services.classification.document_type_klass import is_trans_posting

        transactional = [
            item
            for item in document_types
            if item.enabled
            and item.route_target == ROUTE_PURCHASE
            and is_trans_posting(item)
        ]
        if not transactional:
            return None
        return min(transactional, key=lambda row: row.classifier.priority)

    return None


def get_dt_catalog_entry(
    code: str,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
) -> DtCatalogEntry:
    """Machine catalog metadata for a document type code (org record only)."""
    token = (code or "").strip().upper()
    classification_hints = (
        _org_classification_hints(dt_definition) if dt_definition is not None else ()
    )
    return DtCatalogEntry(
        code=token,
        classification_hints=classification_hints,
        negative_hints=(),
        cross_field_rules=(),
        field_overrides={},
        azure_di_profile="",
        fallback_if_unknown_subtype="",
    )


def shipped_matrix_slot_for_org_row(defn: DocumentTypeDefinition) -> str | None:
    """Shipped matrix code whose catalogue identity applies to this org row, if any.

    Org catalogue codes (DT-01, DT-02, …) are independent sequence slots. When a tenant
    repurposes org DT-04 for a custom non-PO invoice, shipped DT-04 (credit note) metadata
    must not apply — even though the codes collide.
    """
    org_code = (defn.code or "").strip().upper()
    if not org_code:
        return None
    matrix = (defn.matrix_template_code or "").strip().upper()
    if matrix:
        return matrix
    if _org_uses_shipped_classification_metadata(defn, org_code):
        return org_code
    return None


def _shipped_defaults_lookup_code(
    code: str,
    dt_definition: DocumentTypeDefinition | None,
) -> str:
    if dt_definition is None:
        return code
    slot = shipped_matrix_slot_for_org_row(dt_definition)
    return slot or code


def _org_classification_hints(defn: DocumentTypeDefinition) -> tuple[str, ...]:
    seen: set[str] = set()
    hints: list[str] = []
    for raw in (defn.title, defn.short_title):
        token = str(raw or "").strip()
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        hints.append(token)
    return tuple(hints)


def _shipped_reference_titles(code: str) -> tuple[str, str]:
    for row in load_shipped_default_document_types():
        if row.code.upper() == code.upper():
            return str(row.title or "").strip(), str(row.short_title or "").strip()
    return "", ""


def _org_uses_shipped_classification_metadata(
    defn: DocumentTypeDefinition,
    shipped_lookup: str,
) -> bool:
    """True when org row still aligns with shipped template (not repurposed)."""
    matrix = (defn.matrix_template_code or "").strip().upper()
    if matrix and matrix != (defn.code or "").strip().upper():
        return True
    shipped_title, shipped_short = _shipped_reference_titles(shipped_lookup)
    if not shipped_title and not shipped_short:
        return False
    org_title = str(defn.title or "").strip().casefold()
    org_short = str(defn.short_title or "").strip().casefold()
    shipped_title_cf = shipped_title.casefold()
    shipped_short_cf = shipped_short.casefold()
    return org_title in {shipped_title_cf, shipped_short_cf} or org_short in {
        shipped_title_cf,
        shipped_short_cf,
    }


def playbook_profile_for_dt(defn: DocumentTypeDefinition) -> str:
    """Org playbook profile only — no runtime fallback to shipped catalogue."""
    return (defn.playbook_profile or "").strip().lower()


def extraction_fields_for_dt(defn: DocumentTypeDefinition) -> list[str]:
    """Org extraction fields only — no runtime fallback to shipped catalogue."""
    return [str(key).strip().lower() for key in (defn.extraction_fields or []) if str(key).strip()]


def classification_hints_for_dt(
    code: str,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
) -> tuple[list[str], list[str]]:
    """Positive and negative classification hints for LLM classify prompts."""
    entry = get_dt_catalog_entry(code, dt_definition=dt_definition)
    return list(entry.classification_hints), list(entry.negative_hints)


def cross_field_rules_for_dt(
    code: str,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
) -> list[str]:
    return list(get_dt_catalog_entry(code, dt_definition=dt_definition).cross_field_rules)


def clear_document_type_catalog_cache() -> None:
    try:
        load_document_type_catalog.cache_clear()
    except RuntimeError:
        pass
