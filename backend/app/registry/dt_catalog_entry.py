"""Document type catalog machine metadata (shipped defaults)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DtCatalogEntry:
    code: str
    classification_hints: tuple[str, ...] = ()
    negative_hints: tuple[str, ...] = ()
    cross_field_rules: tuple[str, ...] = ()
    field_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    azure_di_profile: str = ""
    fallback_if_unknown_subtype: str = "generic_financial_document"
