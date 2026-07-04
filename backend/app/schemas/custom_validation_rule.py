"""User-defined per-DT validation rules (field-level)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.schemas.validation_rule import ValidationSeverity

CustomValidationOperator = Literal[
    "present",
    "absent",
    "contains",
    "not_contains",
    "gte",
    "lte",
]

CUSTOM_VALIDATION_OPERATORS = frozenset(
    {"present", "absent", "contains", "not_contains", "gte", "lte"}
)


class CustomValidationRule(BaseModel):
    id: str = Field(default_factory=lambda: f"cv-{uuid4().hex[:12]}")
    name: str = Field(..., min_length=1, max_length=120)
    field: str = Field(..., min_length=1, max_length=64)
    operator: CustomValidationOperator = "present"
    value: str = ""
    enabled: bool = True
    severity: ValidationSeverity = "block"

    @field_validator("field")
    @classmethod
    def _normalize_field(cls, value: str) -> str:
        from app.services.classification.document_type_field_keys import is_valid_extraction_field_key

        key = value.strip().lower().replace(" ", "_")
        if not key or not is_valid_extraction_field_key(key):
            raise ValueError(f"Invalid field key: {value}")
        return key

    @field_validator("operator", mode="before")
    @classmethod
    def _normalize_operator(cls, value: Any) -> str:
        token = str(value or "present").strip().lower()
        if token not in CUSTOM_VALIDATION_OPERATORS:
            raise ValueError(f"Unknown custom validation operator: {value}")
        return token


def normalize_custom_validation_rules(value: Any) -> list[CustomValidationRule]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[CustomValidationRule] = []
    for item in value:
        if isinstance(item, CustomValidationRule):
            row = item
        elif isinstance(item, dict):
            try:
                row = CustomValidationRule.model_validate(item)
            except Exception:
                continue
        else:
            continue
        if row.id in seen:
            continue
        seen.add(row.id)
        out.append(row)
    return out
