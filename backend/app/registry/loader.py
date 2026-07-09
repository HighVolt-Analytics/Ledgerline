"""Load universal field registry from shipped JSON."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.registry.field_definition import FieldDefinition, FieldRegistry, JurisdictionFieldVariant

logger = logging.getLogger(__name__)


def _catalog_path() -> Path:
    from app.config import get_settings

    return Path(get_settings().field_registry_path)


def _parse_jurisdiction_variants(raw: Any) -> dict[str, JurisdictionFieldVariant]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, JurisdictionFieldVariant] = {}
    for country, value in raw.items():
        token = str(country or "").strip().upper()
        if not token or not isinstance(value, dict):
            continue
        out[token] = JurisdictionFieldVariant(
            name=str(value.get("name") or "Tax ID").strip(),
            regex=str(value.get("regex")).strip() if value.get("regex") else None,
            checksum=str(value.get("checksum")).strip() if value.get("checksum") else None,
        )
    return out


def _parse_field(key: str, raw: dict[str, Any]) -> FieldDefinition:
    synonyms = raw.get("synonyms") or []
    if isinstance(synonyms, str):
        synonyms = [part.strip() for part in synonyms.split(",") if part.strip()]
    elif isinstance(synonyms, list):
        synonyms = [str(part).strip() for part in synonyms if str(part).strip()]
    else:
        synonyms = []

    confuse = raw.get("do_not_confuse_with") or []
    if isinstance(confuse, str):
        confuse = [part.strip() for part in confuse.split(",") if part.strip()]
    elif isinstance(confuse, list):
        confuse = [str(part).strip() for part in confuse if str(part).strip()]
    else:
        confuse = []

    priority = raw.get("source_priority") or ["llm", "azure_di", "layout_kv", "regex"]
    if isinstance(priority, list):
        priority_tuple = tuple(str(p).strip() for p in priority if str(p).strip())
    else:
        priority_tuple = ("llm", "azure_di", "layout_kv", "regex")

    aliases = raw.get("storage_aliases") or []
    if isinstance(aliases, list):
        alias_tuple = tuple(str(a).strip() for a in aliases if str(a).strip())
    else:
        alias_tuple = ()

    return FieldDefinition(
        key=key,
        label=str(raw.get("label") or key.replace("_", " ").title()).strip(),
        data_type=str(raw.get("data_type") or "string").strip().lower(),
        category=str(raw.get("category") or "general").strip().lower(),
        posting_critical=bool(raw.get("posting_critical", False)),
        grounding_required=bool(raw.get("grounding_required", True)),
        synonyms=tuple(synonyms),
        extraction_hint=str(raw.get("extraction_hint") or "").strip(),
        finance_role=str(raw.get("finance_role") or "").strip(),
        do_not_confuse_with=tuple(confuse),
        jurisdiction_variants=_parse_jurisdiction_variants(raw.get("jurisdiction_variants")),
        source_priority=priority_tuple,
        storage_aliases=alias_tuple,
    )


def load_field_registry_from_path(path: Path) -> FieldRegistry:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("field registry must be a JSON object")
    version = str(raw.get("version") or "1")
    entries = raw.get("fields")
    if not isinstance(entries, list):
        raise ValueError("field registry.fields must be a JSON array")
    fields: dict[str, FieldDefinition] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        if not key:
            continue
        fields[key] = _parse_field(key, item)
    if not fields:
        raise ValueError("field registry contains no fields")
    return FieldRegistry(fields=fields, version=version)


@lru_cache
def get_field_registry() -> FieldRegistry:
    path = _catalog_path()
    if not path.is_file():
        raise FileNotFoundError(f"field registry not found: {path}")
    return load_field_registry_from_path(path)


def clear_field_registry_cache() -> None:
    get_field_registry.cache_clear()
