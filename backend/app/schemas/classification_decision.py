"""Classification compare output and review reason codes."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReviewReason(str, Enum):
    OCR_FAILED = "OCR_FAILED"
    OCR_SPARSE = "OCR_SPARSE"
    IMAGE_QUALITY_LOW = "IMAGE_QUALITY_LOW"
    FIELD_CONFIDENCE_LOW = "FIELD_CONFIDENCE_LOW"
    VENDOR_CLASSIFICATION_DRIFT = "VENDOR_CLASSIFICATION_DRIFT"
    CLASSIFIER_RULE_MISMATCH = "CLASSIFIER_RULE_MISMATCH"
    LLM_INVALID = "LLM_INVALID"
    LLM_LOW_CONF = "LLM_LOW_CONF"
    DT_MISMATCH = "DT_MISMATCH"
    DT_NOT_IN_CATALOGUE = "DT_NOT_IN_CATALOGUE"
    DT_DISABLED = "DT_DISABLED"
    EXTRACTION_GAP = "EXTRACTION_GAP"
    PERSPECTIVE_AMBIGUOUS = "PERSPECTIVE_AMBIGUOUS"
    ROUTE_MISSING = "ROUTE_MISSING"
    PLAYBOOK_BLOCK = "PLAYBOOK_BLOCK"
    NEVER_AUTO_POLICY = "NEVER_AUTO_POLICY"
    POLICY_LOW_CONF = "POLICY_LOW_CONF"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class PolicyDtScore(BaseModel):
    code: str
    confidence: float
    required_present: list[str] = Field(default_factory=list)
    required_missing: list[str] = Field(default_factory=list)
    absent_violations: list[str] = Field(default_factory=list)


class PolicyScoreResult(BaseModel):
    winner_dt: str
    winner_confidence: float
    scores: list[PolicyDtScore] = Field(default_factory=list)


class ClassificationDecision(BaseModel):
    auto_eligible: bool = False
    confirmed_dt: str = ""
    confirmed_confidence: float = 0.0
    review_reasons: list[ReviewReason] = Field(default_factory=list)
    llm_suggested_dt: str = ""
    llm_confidence: float = 0.0
    llm_reasoning: str = ""
    policy_winner_dt: str = ""
    policy_winner_confidence: float = 0.0
    policy_scores: list[PolicyDtScore] = Field(default_factory=list)
    perspective: str = ""  # purchase | sales | unknown
    audit_detail: dict[str, Any] = Field(default_factory=dict)
