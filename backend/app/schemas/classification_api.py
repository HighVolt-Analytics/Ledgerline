"""Classification review API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClassificationResolveRequest(BaseModel):
    confirmed_dt: str = Field(..., min_length=1, max_length=16)
    reprocess: bool = True


class ClassificationReviewItem(BaseModel):
    invoice_id: int
    document_ref: str | None = None
    status: str
    evaluation_status: str | None = None
    llm_suggested_dt: str | None = None
    llm_confidence: float | None = None
    policy_winner_dt: str | None = None
    document_type_code: str | None = None
    review_reasons: list[str] = Field(default_factory=list)
    document_ai_provider: str | None = None


class DocumentTypeRecognitionTestRequest(BaseModel):
    draft_document_type: dict[str, Any]
    document_text: str = ""
    document_heading: str = ""
    email_sender: str = ""
    attachment_name: str = ""


class DocumentTypeRecognitionTestResponse(BaseModel):
    matches: bool
    match_rules_passed: bool
    exclude_rules_passed: bool
    summary: str
    classifier_enabled: bool
