"""Load DT-xx catalogue from org rule book config."""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition

ROUTE_PURCHASE = "Purchase Management"
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
}

DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN = 0.65


def _catalog_path() -> Path:
    return Path(get_settings().document_types_catalog_path)


def _parse_catalog_items(raw: object) -> list[DocumentTypeDefinition]:
    if not isinstance(raw, list):
        raise ValueError("document types catalogue must be a JSON array")
    return [DocumentTypeDefinition.model_validate(item) for item in raw]


def load_shipped_default_document_types() -> list[DocumentTypeDefinition]:
    """Reference catalogue for tests and export scripts — not used for org rule book backfill."""
    from app.services.document_type_field_defaults import (
        default_absent_fields,
        default_extraction_fields,
        default_min_route_confidence,
        default_required_fields,
        default_validation_profile,
    )

    path = _catalog_path()
    items = _parse_catalog_items(json.loads(path.read_text(encoding="utf-8")))
    seeded: list[DocumentTypeDefinition] = []
    for item in items:
        route = DEFAULT_DOCUMENT_TYPE_ROUTE_TARGETS.get(item.code.upper(), ROUTE_VAULT)
        code = item.code.upper()
        seeded.append(
            item.model_copy(
                update={
                    "route_target": route,
                    "enabled": True,
                    "required_fields": default_required_fields(code),
                    "absent_fields": default_absent_fields(code),
                    "extraction_fields": default_extraction_fields(code),
                    "min_route_confidence": default_min_route_confidence(code),
                    "validation_profile": default_validation_profile(code),
                    "bundle_mandatory": list(item.bundle_mandatory),
                    "bundle_conditional": list(item.bundle_conditional),
                    "extraction": [],
                    "checks": [],
                    "match": [],
                    "approval": [],
                    "accounting": [],
                    "special": [],
                }
            )
        )
    return seeded


@lru_cache
def load_document_type_catalog(tenant_id: int) -> tuple[DocumentTypeDefinition, ...]:
    from app.schemas.rule_book_config import validate_rule_book_config_payload
    from app.services.rule_book_config_io import load_rule_book_config_dict

    raw = load_rule_book_config_dict(tenant_id)
    config = validate_rule_book_config_payload(raw)
    return tuple(config.document_types)


def get_document_type_definition(
    code: str,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
) -> DocumentTypeDefinition | None:
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    catalog = document_types
    if catalog is None:
        if tenant_id is None:
            return None
        catalog = load_document_type_catalog(tenant_id)
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
    from app.services.document_type_scoring_service import effective_min_route_confidence

    return effective_min_route_confidence(definition)


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
    if definition is None or not definition.enabled:
        return None
    return definition.route_target


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
        transactional = [
            item
            for item in document_types
            if item.enabled
            and item.route_target == ROUTE_PURCHASE
            and item.klass == "Transactional"
            and (item.posting or "").strip().lower() != "no"
        ]
        if not transactional:
            return None
        return min(transactional, key=lambda row: row.classifier.priority)

    return None


def clear_document_type_catalog_cache() -> None:
    load_document_type_catalog.cache_clear()
