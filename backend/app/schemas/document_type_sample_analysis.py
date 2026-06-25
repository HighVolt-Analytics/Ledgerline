"""Schemas for document-type sample analysis (Rule Book editor)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationRuleProposal(BaseModel):
    code: str
    enabled: bool = True
    severity: str = "block"


class DocumentTypeSampleFileResult(BaseModel):
    filename: str
    recognition_signals: list[str] = Field(default_factory=list)
    extraction_fields: list[str] = Field(default_factory=list)
    document_heading: str | None = None
    parse_confidence: str | None = None
    routed_code: str | None = None
    routed_confidence: float | None = None
    route_needs_review: bool = False
    route_conflicts: list[str] = Field(default_factory=list)
    matches_expected: bool | None = None
    route_alternatives: list[dict[str, object]] = Field(default_factory=list)


class DocumentTypeClassifyPreviewCandidate(BaseModel):
    code: str
    confidence: float
    reason: str
    needs_review: bool = False
    priority: int = 100


class DocumentTypeSampleProposal(BaseModel):
    """Merged settings suggested from one or more sample uploads."""

    recognition_signals: list[str] = Field(default_factory=list)
    classifier_layout: str = "any_signal"
    extraction_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    absent_fields: list[str] = Field(default_factory=list)
    one_line: str = ""
    suggested_title: str | None = None
    suggested_short_title: str | None = None
    klass: str = "Transactional"
    posting: str = "Yes"
    route_target: str = "Vault"
    playbook_profile: str = "standard_transactional"
    purchase_bundle_role: str = ""
    match_mode: str = "none"
    approval_mode: str = "touchless_on_clean_match"
    validation_profile: str = ""
    validation_rules: list[ValidationRuleProposal] = Field(default_factory=list)
    bundle_mandatory: list[str] = Field(default_factory=list)
    bundle_conditional: list[str] = Field(default_factory=list)
    min_route_confidence: float = 0.65
    samples: list[DocumentTypeSampleFileResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    apply_ready: bool = False
    apply_block_reason: str | None = None
