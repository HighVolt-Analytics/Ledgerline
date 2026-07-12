"""Extraction field contracts — per-field policy for resolution and persistence."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FieldType(StrEnum):
    STRING = "string"
    AMOUNT = "amount"
    DATE = "date"
    CURRENCY = "currency"
    PARTY = "party"
    IDENTIFIER = "identifier"
    LINE_ITEMS = "line_items"
    CUSTOM = "custom"
    TEXT = "text"
    BANK = "bank"


class FieldSource(StrEnum):
    SEMANTIC_DI = "semantic_di"
    LAYOUT_KV = "layout_kv"
    LAYOUT_TABLE = "layout_table"
    REGEX = "regex"
    LLM = "llm"
    DERIVED = "derived"
    # Legacy aliases accepted in priority lists
    AZURE_DI = "azure_di"


class ResolutionStatus(StrEnum):
    ACCEPTED = "accepted"
    ACCEPTED_WITH_WARNING = "accepted_with_warning"
    REJECTED = "rejected"
    MISSING = "missing"
    REVIEW_REQUIRED = "review_required"


# Map legacy registry source names → FieldSource
_SOURCE_ALIASES: dict[str, FieldSource] = {
    "azure_di": FieldSource.SEMANTIC_DI,
    "semantic_di": FieldSource.SEMANTIC_DI,
    "layout_kv": FieldSource.LAYOUT_KV,
    "layout_table": FieldSource.LAYOUT_TABLE,
    "regex": FieldSource.REGEX,
    "llm": FieldSource.LLM,
    "derived": FieldSource.DERIVED,
}


def normalize_field_source(raw: str | FieldSource) -> FieldSource:
    token = str(raw or "").strip().lower()
    return _SOURCE_ALIASES.get(token, FieldSource.LLM)


class ExtractionFieldContract(BaseModel):
    """Per-field extraction contract — governs request, trust, and persistence."""

    key: str
    field_type: FieldType = FieldType.STRING
    canonical: bool = True
    target_column: str = ""  # InvoiceData attr or extracted_fields key
    applies_to_routes: tuple[str, ...] = ()
    required: bool = False
    allowed_sources: tuple[str, ...] = (
        FieldSource.SEMANTIC_DI,
        FieldSource.LAYOUT_KV,
        FieldSource.REGEX,
        FieldSource.LLM,
    )
    authoritative_source_order: tuple[str, ...] = (
        FieldSource.SEMANTIC_DI,
        FieldSource.LAYOUT_KV,
        FieldSource.REGEX,
        FieldSource.LLM,
    )
    min_confidence: float | None = None
    grounding_required: bool = True
    validation_rules: tuple[str, ...] = ()
    fallback_policy: str = "gap_fill"
    custom_label_aliases: tuple[str, ...] = ()
    query_field_name: str | None = None
    route_overrides: dict[str, Any] = Field(default_factory=dict)
    persist_when_unconfigured: bool = False
    review_if_missing: bool = False
    review_if_low_confidence: bool = True

    def source_rank(self, source: str | FieldSource) -> int:
        normalized = normalize_field_source(source).value
        order = [normalize_field_source(s).value for s in self.authoritative_source_order]
        try:
            return order.index(normalized)
        except ValueError:
            return len(order) + 10

    def allows_source(self, source: str | FieldSource) -> bool:
        normalized = normalize_field_source(source).value
        allowed = {normalize_field_source(s).value for s in self.allowed_sources}
        return normalized in allowed


class FieldCandidate(BaseModel):
    source: str
    value: Any = None
    confidence: float | None = None
    grounded: bool = False
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class FieldResolutionResult(BaseModel):
    key: str
    value: Any = None
    chosen_source: str | None = None
    confidence: float | None = None
    resolution_status: ResolutionStatus = ResolutionStatus.MISSING
    review_reason: str | None = None
    rejected_candidates: list[dict[str, Any]] = Field(default_factory=list)
    grounded: bool = False
    target_column: str = ""

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": _audit_value(self.value),
            "chosen_source": self.chosen_source,
            "confidence": self.confidence,
            "resolution_status": self.resolution_status.value,
            "review_reason": self.review_reason,
            "grounded": self.grounded,
            "target_column": self.target_column,
            "rejected_candidates": self.rejected_candidates,
        }


def _audit_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__float__") and type(value).__name__ == "Decimal":
        return str(value)
    if isinstance(value, list):
        return [_audit_value(v) for v in value[:50]]
    if isinstance(value, dict):
        return {str(k): _audit_value(v) for k, v in list(value.items())[:30]}
    token = str(value)
    return token if len(token) <= 500 else token[:500]


def contracts_to_selected_keys(contracts: list[ExtractionFieldContract]) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for contract in contracts:
        token = (contract.key or "").strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        keys.append(token)
    return keys


def required_keys_from_contracts(contracts: list[ExtractionFieldContract]) -> list[str]:
    return [c.key for c in contracts if c.required]
