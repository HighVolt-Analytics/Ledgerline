"""Field registry dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JurisdictionFieldVariant:
    name: str = "Tax ID"
    regex: str | None = None
    checksum: str | None = None


@dataclass(frozen=True)
class FieldDefinition:
    key: str
    label: str
    data_type: str = "string"
    category: str = "general"
    posting_critical: bool = False
    grounding_required: bool = True
    synonyms: tuple[str, ...] = ()
    extraction_hint: str = ""
    finance_role: str = ""
    do_not_confuse_with: tuple[str, ...] = ()
    deprioritized_label_qualifiers: tuple[str, ...] = ()
    jurisdiction_variants: dict[str, JurisdictionFieldVariant] = field(default_factory=dict)
    source_priority: tuple[str, ...] = ("llm", "azure_di", "layout_kv", "regex")
    storage_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldRegistry:
    fields: dict[str, FieldDefinition]
    version: str = "1"
