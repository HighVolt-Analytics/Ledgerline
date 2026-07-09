"""Per-field scalar fusion using registry source_priority."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.services.extraction.extraction_field_values import configured_extraction_keys


@dataclass(frozen=True)
class FusionResult:
    field_key: str
    value: Any
    source: str
    agreement_score: float


def _source_priority(defn: DocumentTypeDefinition | None, field_key: str) -> list[str]:
    if defn is None:
        return ["azure_di", "llm", "regex", "layout"]
    overrides = defn.field_overrides or {}
    row = overrides.get(field_key) if isinstance(overrides, dict) else None
    if isinstance(row, dict):
        priority = row.get("source_priority")
        if isinstance(priority, list) and priority:
            return [str(item).strip().lower() for item in priority if str(item).strip()]
    return ["azure_di", "llm", "regex", "layout"]


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def fuse_scalar_field(
    field_key: str,
    sources: dict[str, Any],
    *,
    dt_definition: DocumentTypeDefinition | None = None,
) -> FusionResult | None:
    priority = _source_priority(dt_definition, field_key)
    populated = {name: value for name, value in sources.items() if not _is_empty(value)}
    if not populated:
        return None
    values = {str(v) for v in populated.values()}
    agreement_score = 1.0 if len(values) == 1 else max(0.0, 1.0 - (len(values) - 1) * 0.25)
    for source_name in priority:
        if source_name in populated:
            return FusionResult(
                field_key=field_key,
                value=populated[source_name],
                source=source_name,
                agreement_score=agreement_score,
            )
    first_name = next(iter(populated))
    return FusionResult(
        field_key=field_key,
        value=populated[first_name],
        source=first_name,
        agreement_score=agreement_score,
    )


def fuse_scalar_fields(
    sources_by_field: dict[str, dict[str, Any]],
    *,
    dt_definition: DocumentTypeDefinition | None = None,
    field_keys: Sequence[str] | None = None,
) -> dict[str, FusionResult]:
    keys = list(field_keys) if field_keys is not None else (
        configured_extraction_keys(dt_definition) if dt_definition else list(sources_by_field)
    )
    out: dict[str, FusionResult] = {}
    for key in keys:
        if key == "line_items":
            continue
        field_sources = sources_by_field.get(key, {})
        result = fuse_scalar_field(key, field_sources, dt_definition=dt_definition)
        if result is not None:
            out[key] = result
    return out


def apply_fusion_to_invoice_data(parsed: Any, fused: dict[str, FusionResult]) -> Any:
    from dataclasses import replace

    updates: dict[str, Any] = {}
    for key, result in fused.items():
        if hasattr(parsed, key):
            current = getattr(parsed, key, None)
            if _is_empty(current) or str(current) != str(result.value):
                if isinstance(result.value, str) and hasattr(parsed, key):
                    field_type = type(getattr(parsed, key, None))
                    if field_type is Decimal:
                        try:
                            updates[key] = Decimal(str(result.value))
                            continue
                        except Exception:
                            pass
                updates[key] = result.value
    if not updates:
        return parsed
    return replace(parsed, **updates)
