"""Structured LLM output for document-type sample proposals."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.classification.document_classifier_builder import _SIGNAL_CONDITIONS
from app.services.classification.document_type_field_keys import is_valid_extraction_field_key
from app.services.classification.playbook_profile_catalog import PROFILE_PRESETS

_VALID_SIGNALS = frozenset(_SIGNAL_CONDITIONS) | frozenset(
    {"has_po_reference", "has_invoice_number", "has_total_amount"}
)
_VALID_LAYOUTS = frozenset({"grouped", "supporting_doc", "any_signal", "all_signals"})
_PLAYBOOK_PROFILE_IDS = frozenset(PROFILE_PRESETS)


class LlmSampleProposal(BaseModel):
    playbook_profile: str = "standard_transactional"
    recognition_signals: list[str] = Field(default_factory=list)
    extraction_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    absent_fields: list[str] = Field(default_factory=list)
    classifier_layout: str = "grouped"
    llm_prompt: str = ""
    suggested_title: str | None = None
    purchase_bundle_role: str = ""
    confidence: float = 0.0
    reasoning: str = ""

    @field_validator("playbook_profile")
    @classmethod
    def _validate_playbook(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized in _PLAYBOOK_PROFILE_IDS:
            return normalized
        return "standard_transactional"

    @field_validator("recognition_signals")
    @classmethod
    def _validate_signals(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            signal = raw.strip()
            if signal in _VALID_SIGNALS and signal not in cleaned:
                cleaned.append(signal)
        return cleaned

    @field_validator("extraction_fields", "required_fields", "absent_fields")
    @classmethod
    def _validate_fields(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            key = raw.strip().lower()
            if key in {"document_heading"} or is_valid_extraction_field_key(key):
                if key not in cleaned:
                    cleaned.append(key)
        return cleaned

    @field_validator("classifier_layout")
    @classmethod
    def _validate_layout(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        return normalized if normalized in _VALID_LAYOUTS else "grouped"

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value or 0.0)))

    @field_validator("purchase_bundle_role")
    @classmethod
    def _validate_bundle_role(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        return normalized if normalized in {"", "po", "grn"} else ""
