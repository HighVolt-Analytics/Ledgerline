"""Shipped per-DT field and validation defaults (JSON config, not code)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


def _defaults_path() -> Path:
    return Path(get_settings().document_type_defaults_path)


@lru_cache
def _load_defaults_index() -> dict[str, dict[str, Any]]:
    path = _defaults_path()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("document type defaults file must be a JSON object")
    return {str(code).strip().upper(): value for code, value in raw.items()}


def _row(code: str) -> dict[str, Any]:
    row = _load_defaults_index().get(code.strip().upper(), {})
    return row if isinstance(row, dict) else {}


def default_required_fields(code: str) -> list[str]:
    values = _row(code).get("required_fields")
    return list(values) if isinstance(values, list) else []


def default_extraction_fields(code: str) -> list[str]:
    values = _row(code).get("extraction_fields")
    if isinstance(values, list) and values:
        return list(values)
    return default_required_fields(code)


def default_absent_fields(code: str) -> list[str]:
    values = _row(code).get("absent_fields")
    return list(values) if isinstance(values, list) else []


def default_min_route_confidence(code: str) -> float:
    value = _row(code).get("min_route_confidence")
    return float(value) if value is not None else 0.65


def default_validation_profile(code: str) -> str:
    value = _row(code).get("validation_profile")
    return str(value) if value else ""


def default_playbook_profile(code: str) -> str:
    value = _row(code).get("playbook_profile")
    return str(value).strip().lower() if value else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def default_classification_hints(code: str) -> list[str]:
    return _string_list(_row(code).get("classification_hints"))


def default_negative_hints(code: str) -> list[str]:
    return _string_list(_row(code).get("negative_hints"))


def default_cross_field_rules(code: str) -> list[str]:
    return _string_list(_row(code).get("cross_field_rules"))


def default_field_overrides(code: str) -> dict[str, dict[str, Any]]:
    raw = _row(code).get("field_overrides")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        token = str(key or "").strip().lower()
        if not token or not isinstance(value, dict):
            continue
        out[token] = dict(value)
    return out


def default_azure_di_profile(code: str) -> str:
    value = _row(code).get("azure_di_profile")
    return str(value).strip() if value else ""


def default_fallback_if_unknown_subtype(code: str) -> str:
    value = _row(code).get("fallback_if_unknown_subtype")
    token = str(value).strip() if value else ""
    return token or "generic_financial_document"


def clear_document_type_defaults_cache() -> None:
    _load_defaults_index.cache_clear()
