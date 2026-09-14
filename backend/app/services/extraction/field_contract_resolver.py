"""Resolve extraction field contracts for a document type + route."""

from __future__ import annotations

from typing import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import extraction_fields_for_dt
from app.services.classification.document_type_field_keys import (
    is_valid_extraction_field_key,
    normalize_extraction_field_keys,
)
from app.services.classification.document_type_playbook_profile_service import (
    effective_playbook_profile,
)
from app.services.extraction.field_contracts import (
    ExtractionFieldContract,
    contracts_to_selected_keys,
)
from app.services.extraction.field_registry import (
    COMMERCIAL_FALLBACK_KEYS,
    ROUTE_DEFAULT_FIELD_KEYS,
    TRANSACTIONAL_EXTRACTION_ROUTES,
    build_field_template,
)
from app.services.extraction.routing.routes import ExtractionRoute
from app.services.rule_book.extraction_field_config_audit import (
    RECOMMENDED_FIELDS_BY_PLAYBOOK,
    RECOMMENDED_FIELDS_BY_ROUTE,
)

_NON_TRANSACTIONAL_PLAYBOOKS = frozenset(
    {
        "supporting",
        "reconciliation",
        "non_actionable",
        "informational",
        "master_data",
        "compliance_route",
    }
)


def _uniq_keys(*groups: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for raw in group:
            token = str(raw or "").strip().lower()
            if not token or token in seen:
                continue
            if not is_valid_extraction_field_key(token):
                continue
            seen.add(token)
            out.append(token)
    return out


def _org_required_keys(defn: DocumentTypeDefinition) -> set[str]:
    return {
        str(k).strip().lower()
        for k in (defn.required_fields or [])
        if str(k or "").strip()
    }


def _org_extraction_keys(defn: DocumentTypeDefinition) -> list[str]:
    keys = extraction_fields_for_dt(defn)
    if keys:
        return normalize_extraction_field_keys(keys)
    # required-only when extraction_fields empty but required present
    required = [str(k).strip().lower() for k in (defn.required_fields or []) if str(k or "").strip()]
    return normalize_extraction_field_keys(required) if required else []


def _playbook_keys(defn: DocumentTypeDefinition, route: ExtractionRoute) -> list[str]:
    if route not in TRANSACTIONAL_EXTRACTION_ROUTES:
        return []
    profile = (effective_playbook_profile(defn) or "").strip().lower()
    if profile in _NON_TRANSACTIONAL_PLAYBOOKS:
        return []
    keys: list[str] = []
    keys.extend(RECOMMENDED_FIELDS_BY_PLAYBOOK.get(profile, ()))
    route_target = (defn.route_target or "").strip()
    keys.extend(RECOMMENDED_FIELDS_BY_ROUTE.get(route_target, ()))
    if keys and "line_items" not in {k.lower() for k in keys}:
        keys.append("line_items")
    return normalize_extraction_field_keys(keys)


def _route_default_keys(route: ExtractionRoute) -> list[str]:
    return list(ROUTE_DEFAULT_FIELD_KEYS.get(route, ()))


def resolve_extraction_route_for_dt(
    dt_definition: DocumentTypeDefinition | None,
    *,
    confirmed_dt: str = "",
    route: ExtractionRoute | str | None = None,
) -> ExtractionRoute:
    if isinstance(route, ExtractionRoute):
        return route
    if isinstance(route, str) and route.strip():
        try:
            return ExtractionRoute(route.strip().lower())
        except ValueError:
            pass
    from app.services.extraction.routing import route_document_for_extraction

    decision = route_document_for_extraction(confirmed_dt or (dt_definition.code if dt_definition else ""), dt_definition)
    return decision.route


def resolve_extraction_field_contracts_for_dt(
    document_types: Sequence[DocumentTypeDefinition] | None,
    dt_code: str,
    *,
    route: ExtractionRoute | str | None = None,
    dt_definition: DocumentTypeDefinition | None = None,
) -> list[ExtractionFieldContract]:
    """Resolve field contracts for one DT + extraction route."""
    code = (dt_code or "").strip().upper()
    defn = dt_definition
    if defn is None and document_types:
        for row in document_types:
            if not row.enabled:
                continue
            if (row.code or "").strip().upper() == code:
                defn = row
                break
    if defn is None:
        return []

    extraction_route = resolve_extraction_route_for_dt(
        defn, confirmed_dt=code, route=route
    )

    explicit_org = [
        str(k).strip().lower()
        for k in (defn.extraction_fields or [])
        if str(k or "").strip()
    ]
    required = _org_required_keys(defn)
    route_keys = _route_default_keys(extraction_route)
    playbook = _playbook_keys(defn, extraction_route)
    catalog_keys = _org_extraction_keys(defn)

    # Explicit org extraction_fields wins as the universe.
    if explicit_org:
        key_list = _uniq_keys(explicit_org, list(required))
    else:
        key_list = _uniq_keys(catalog_keys, playbook, route_keys, list(required))
        if not key_list and extraction_route in TRANSACTIONAL_EXTRACTION_ROUTES:
            profile = (effective_playbook_profile(defn) or "").strip().lower()
            if profile not in _NON_TRANSACTIONAL_PLAYBOOKS:
                key_list = list(COMMERCIAL_FALLBACK_KEYS)
        # Supporting / unknown stay empty unless org configured

    contracts: list[ExtractionFieldContract] = []
    seen: set[str] = set()
    for key in key_list:
        if key in seen:
            continue
        seen.add(key)
        template = build_field_template(key, required=key in required)
        # Route applicability metadata
        applies = tuple(
            r.value
            for r, keys in ROUTE_DEFAULT_FIELD_KEYS.items()
            if key in keys
        ) or (extraction_route.value,)
        data = template.model_dump()
        data["applies_to_routes"] = applies
        data["required"] = key in required or template.required
        data["review_if_missing"] = key in required
        # Custom fields: DI not allowed unless query_field configured
        if template.field_type.value == "custom" and not template.query_field_name:
            allowed = tuple(
                s
                for s in template.allowed_sources
                if s not in {"semantic_di", "azure_di"}
            )
            data["allowed_sources"] = allowed or ("layout_kv", "regex", "llm")
            data["authoritative_source_order"] = data["allowed_sources"]
        contracts.append(ExtractionFieldContract.model_validate(data))
    return contracts


def selected_keys_from_contracts_for_dt(
    document_types: Sequence[DocumentTypeDefinition],
    dt_code: str,
    *,
    route: ExtractionRoute | str | None = None,
) -> list[str]:
    return contracts_to_selected_keys(
        resolve_extraction_field_contracts_for_dt(document_types, dt_code, route=route)
    )
