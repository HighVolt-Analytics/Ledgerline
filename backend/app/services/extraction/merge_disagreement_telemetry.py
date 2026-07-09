"""Per-field source disagreement telemetry for merge_extraction_sources."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SourceDisagreementRow:
    field_key: str
    sources: dict[str, Any]
    agreed: bool
    chosen_source: str | None = None
    chosen_value: Any = None


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return str(value)


def collect_scalar_disagreements(
    *,
    field_keys: list[str],
    llm_parsed: Any,
    di_parsed: Any | None,
    regex_parsed: Any | None,
    merged: Any,
) -> list[SourceDisagreementRow]:
    rows: list[SourceDisagreementRow] = []
    for key in field_keys:
        if key in {"line_items", "extracted_fields", "raw_fields", "document_text"}:
            continue
        sources: dict[str, Any] = {}
        for source_name, parsed in (
            ("llm", llm_parsed),
            ("azure_di", di_parsed),
            ("regex", regex_parsed),
        ):
            if parsed is None:
                continue
            value = getattr(parsed, key, None)
            if value is not None and str(value).strip():
                sources[source_name] = _serialize_value(value)
        if len(sources) < 2:
            continue
        values = list(sources.values())
        agreed = len({str(v) for v in values}) == 1
        chosen = _serialize_value(getattr(merged, key, None))
        rows.append(
            SourceDisagreementRow(
                field_key=key,
                sources=sources,
                agreed=agreed,
                chosen_value=chosen,
            )
        )
    return rows


def disagreement_audit_detail(rows: list[SourceDisagreementRow]) -> dict[str, object]:
    return {
        "field_count": len(rows),
        "disagreements": [
            {
                "field_key": row.field_key,
                "sources": row.sources,
                "agreed": row.agreed,
                "chosen_value": row.chosen_value,
            }
            for row in rows
            if not row.agreed
        ],
    }
