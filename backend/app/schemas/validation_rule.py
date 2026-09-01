"""Per document-type validation rule configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ValidationSeverity = Literal["block", "warn"]

UNIVERSAL_VALIDATION_RULE_CODES = frozenset({"VR02"})

# User-configurable per document type (Rule Book → Validation).
CONFIGURABLE_VALIDATION_RULE_CODES = frozenset(
    {
        "VR03",
        "VR08",
        "VR01",
        "VR09",
        "VR11",
        "VR12",
        "VR13",
        "VR-PB02",
    }
)

# Backward-compatible alias.
FINANCE_VALIDATION_RULE_CODES = CONFIGURABLE_VALIDATION_RULE_CODES

KNOWN_VALIDATION_RULE_CODES = UNIVERSAL_VALIDATION_RULE_CODES | CONFIGURABLE_VALIDATION_RULE_CODES


class ValidationRuleConfig(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    enabled: bool = True
    severity: ValidationSeverity = "block"

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        token = value.strip().upper()
        if token not in KNOWN_VALIDATION_RULE_CODES:
            raise ValueError(f"Unknown validation rule code: {value}")
        return token


def normalize_validation_rules(value: Any) -> list[ValidationRuleConfig]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[ValidationRuleConfig] = []
    for item in value:
        if isinstance(item, ValidationRuleConfig):
            row = item
        elif isinstance(item, dict):
            try:
                row = ValidationRuleConfig.model_validate(item)
            except Exception:
                continue
        else:
            continue
        if row.code in seen or row.code in UNIVERSAL_VALIDATION_RULE_CODES:
            continue
        if row.code not in CONFIGURABLE_VALIDATION_RULE_CODES:
            continue
        seen.add(row.code)
        out.append(row)
    return out
