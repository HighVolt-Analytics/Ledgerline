"""Application-wide extraction field templates (contracts defaults)."""

from __future__ import annotations

from functools import lru_cache

from app.services.extraction.extraction_field_values import (
    EXTRACTED_ONLY_ATTRS,
    INVOICE_SCALAR_ATTRS,
)
from app.services.extraction.field_contracts import (
    ExtractionFieldContract,
    FieldSource,
    FieldType,
    normalize_field_source,
)
from app.services.extraction.routing.routes import ExtractionRoute

# Transactional routes that may receive commercial fallback fields.
TRANSACTIONAL_EXTRACTION_ROUTES: frozenset[ExtractionRoute] = frozenset(
    {
        ExtractionRoute.INVOICE,
        ExtractionRoute.CREDIT_NOTE,
        ExtractionRoute.DEBIT_NOTE,
        ExtractionRoute.RECEIPT,
        ExtractionRoute.EXPENSE_CLAIM,
    }
)

_DI_FIRST = (
    FieldSource.SEMANTIC_DI,
    FieldSource.LAYOUT_KV,
    FieldSource.REGEX,
    FieldSource.LLM,
)
_LAYOUT_FIRST = (
    FieldSource.LAYOUT_KV,
    FieldSource.REGEX,
    FieldSource.LLM,
    FieldSource.SEMANTIC_DI,
)
_CUSTOM_SOURCES = (
    FieldSource.LAYOUT_KV,
    FieldSource.REGEX,
    FieldSource.LLM,
)
_LINE_ITEM_SOURCES = (
    FieldSource.SEMANTIC_DI,
    FieldSource.LAYOUT_TABLE,
    FieldSource.LLM,
)


def _target_for(key: str) -> tuple[bool, str]:
    if key in INVOICE_SCALAR_ATTRS or key == "line_items":
        return True, key
    if key in EXTRACTED_ONLY_ATTRS:
        return False, key
    return False, key


def _type_for(key: str) -> FieldType:
    if key in {"subtotal", "gst", "gst_rate", "total", "amount_due"}:
        return FieldType.AMOUNT
    if key in {"invoice_date", "due_date"}:
        return FieldType.DATE
    if key == "currency":
        return FieldType.CURRENCY
    if key == "line_items":
        return FieldType.LINE_ITEMS
    if key in {"vendor", "buyer_name", "seller_name"}:
        return FieldType.PARTY
    if key in {
        "invoice_no",
        "po_reference",
        "so_reference",
        "grn_reference",
        "remittance_reference",
        "statement_reference",
        "permit_no",
        "abn",
        "seller_abn",
        "buyer_abn",
    }:
        return FieldType.IDENTIFIER
    if key in {"bank_bsb", "bank_account", "bank_name", "bank_details"}:
        return FieldType.BANK
    if key in {"document_text", "document_heading", "attachment_name"}:
        return FieldType.TEXT
    if key not in INVOICE_SCALAR_ATTRS and key not in EXTRACTED_ONLY_ATTRS:
        return FieldType.CUSTOM
    return FieldType.STRING


def _sources_for(key: str) -> tuple[FieldSource, ...]:
    if key == "line_items":
        return _LINE_ITEM_SOURCES
    if key in {
        "cost_centre",
        "permit_no",
        "remittance_reference",
        "statement_reference",
        "statement_period",
        "grn_reference",
        "so_reference",
    }:
        return _LAYOUT_FIRST
    if _type_for(key) == FieldType.CUSTOM:
        return _CUSTOM_SOURCES
    if key in {"vendor", "invoice_no", "abn", "currency", "total", "subtotal", "gst"}:
        return _DI_FIRST
    return _DI_FIRST


def _priority_from_registry(key: str) -> tuple[str, ...] | None:
    try:
        from app.registry.adapter import get_registry_adapter

        priority = get_registry_adapter().source_priority_for(key)
        if priority:
            return tuple(normalize_field_source(s).value for s in priority)
    except Exception:  # noqa: BLE001 — defensive; registry optional
        return None
    return None


def build_field_template(key: str, *, required: bool = False) -> ExtractionFieldContract:
    """Default contract template for one application field key."""
    token = (key or "").strip().lower()
    canonical, target = _target_for(token)
    field_type = _type_for(token)
    sources = _sources_for(token)
    order = _priority_from_registry(token) or tuple(s.value for s in sources)
    allowed = tuple(s.value for s in sources)
    # Prefer registry order but only keep allowed sources
    filtered_order = tuple(s for s in order if s in set(allowed)) or allowed
    grounding = True
    try:
        from app.registry.adapter import get_registry_adapter

        grounding = bool(get_registry_adapter().grounding_required(token))
    except Exception:  # noqa: BLE001
        grounding = field_type not in {FieldType.TEXT}

    aliases: tuple[str, ...] = ()
    if token == "cost_centre":
        aliases = ("cost centre", "cost center", "project code", "cc")
    elif token == "permit_no":
        aliases = ("permit no", "permit number", "cargo clearance")
    elif token == "currency":
        aliases = ("currency", "ccy")
    elif token == "abn":
        aliases = ("abn", "tax id", "gstin")

    return ExtractionFieldContract(
        key=token,
        field_type=field_type,
        canonical=canonical,
        target_column=target,
        required=required,
        allowed_sources=allowed,
        authoritative_source_order=filtered_order,
        grounding_required=grounding,
        custom_label_aliases=aliases,
        review_if_missing=required,
        review_if_low_confidence=True,
        persist_when_unconfigured=False,
    )


# Route → default field keys (not DT-code matrix).
ROUTE_DEFAULT_FIELD_KEYS: dict[ExtractionRoute, tuple[str, ...]] = {
    ExtractionRoute.INVOICE: (
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "subtotal",
        "gst",
        "total",
        "currency",
        "billing_address",
        "cost_centre",
        "line_items",
    ),
    ExtractionRoute.CREDIT_NOTE: (
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "subtotal",
        "gst",
        "total",
        "currency",
        "line_items",
    ),
    ExtractionRoute.DEBIT_NOTE: (
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "subtotal",
        "gst",
        "total",
        "currency",
        "line_items",
    ),
    ExtractionRoute.RECEIPT: (
        "vendor",
        "invoice_no",
        "invoice_date",
        "total",
        "currency",
        "line_items",
    ),
    ExtractionRoute.EXPENSE_CLAIM: (
        "vendor",
        "invoice_no",
        "invoice_date",
        "total",
        "currency",
        "line_items",
    ),
    ExtractionRoute.PURCHASE_ORDER: (
        "vendor",
        "po_reference",
        "invoice_date",
        "line_items",
    ),
    ExtractionRoute.GRN: (
        "vendor",
        "grn_reference",
        "po_reference",
        "invoice_date",
        "line_items",
    ),
    ExtractionRoute.STATEMENT: (
        "vendor",
        "statement_reference",
        "statement_period",
        "invoice_date",
        "total",
    ),
    ExtractionRoute.REMITTANCE: (
        "vendor",
        "remittance_reference",
        "total",
        "invoice_date",
        "currency",
    ),
    ExtractionRoute.SUPPORTING_DOCUMENT: (),
    ExtractionRoute.UNKNOWN: (),
}

COMMERCIAL_FALLBACK_KEYS: tuple[str, ...] = (
    "vendor",
    "abn",
    "invoice_no",
    "invoice_date",
    "due_date",
    "po_reference",
    "subtotal",
    "gst",
    "total",
    "currency",
    "billing_address",
    "cost_centre",
    "line_items",
)


@lru_cache(maxsize=1)
def all_known_field_templates() -> dict[str, ExtractionFieldContract]:
    keys = set(COMMERCIAL_FALLBACK_KEYS)
    for route_keys in ROUTE_DEFAULT_FIELD_KEYS.values():
        keys.update(route_keys)
    keys.update(INVOICE_SCALAR_ATTRS)
    keys.update(EXTRACTED_ONLY_ATTRS)
    keys.add("permit_no")
    keys.add("line_items")
    return {key: build_field_template(key) for key in sorted(keys)}
