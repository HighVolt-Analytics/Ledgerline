"""Document type catalogue (DT-xx master matrix)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.custom_validation_rule import (
    CustomValidationRule,
    normalize_custom_validation_rules,
)
from app.schemas.playbook_policy import (
    ApprovalPolicy,
    MatchPolicy,
    normalize_approval_policy,
    normalize_match_policy,
)
from app.schemas.validation_rule import ValidationRuleConfig, normalize_validation_rules


DocumentTypeRouteTarget = Literal[
    "Purchase Management",
    "Expenses Management",
    "Team Expenses",
    "Vault",
]

PurchaseBundleRole = Literal["", "po", "grn"]


def _empty_classifier_root() -> dict[str, Any]:
    return {"type": "group", "operator": "AND", "children": []}


class DocumentTypeSampleAnalysis(BaseModel):
    """Record that sample files were analyzed in the Rule Book editor (metadata only)."""

    analyzed_at: str = Field(alias="analyzedAt")
    filenames: list[str] = Field(default_factory=list)
    file_count: int = Field(default=0, ge=0, alias="fileCount")
    applied_at: str | None = Field(default=None, alias="appliedAt")
    recognition_signals: list[str] = Field(default_factory=list, alias="recognitionSignals")

    model_config = {"populate_by_name": True}


class DocumentTypeClassifier(BaseModel):
    """User-defined conditions that classify documents to this DT code."""

    enabled: bool = False
    priority: int = Field(default=100, ge=1)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    root: dict[str, Any] = Field(default_factory=_empty_classifier_root)

    @field_validator("root")
    @classmethod
    def _validate_root(cls, value: Any) -> dict[str, Any]:
        from app.schemas.rule_book_config import RuleConditionGroup
        from app.services.rule_engine import sanitize_condition_group

        validated = RuleConditionGroup.model_validate(value).model_dump()
        return sanitize_condition_group(validated)


class DocumentTypeDefinition(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    title: str
    short_title: str = Field(alias="shortTitle")
    klass: str
    posting: str
    fraud_risk: str = Field(alias="fraudRisk")
    one_line: str = Field(alias="oneLine")
    route_target: DocumentTypeRouteTarget = Field(
        default="Vault",
        alias="routeTarget",
    )
    enabled: bool = True
    classifier: DocumentTypeClassifier = Field(default_factory=DocumentTypeClassifier)
    classifier_customized: bool = Field(default=False, alias="classifierCustomized")
    matrix_template_code: str = Field(
        default="",
        max_length=16,
        alias="matrixTemplateCode",
        description="Shipped matrix template id (e.g. DT-07); org code is assigned separately.",
    )
    required_fields: list[str] = Field(default_factory=list, alias="requiredFields")
    absent_fields: list[str] = Field(default_factory=list, alias="absentFields")
    min_route_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        alias="minRouteConfidence",
    )
    validation_profile: str = Field(default="", alias="validationProfile")
    playbook_profile: str = Field(default="", alias="playbookProfile")
    match_policy: MatchPolicy | None = Field(default=None, alias="matchPolicy")
    approval_policy: ApprovalPolicy | None = Field(
        default=None,
        alias="approvalPolicy",
    )
    validation_rules: list[ValidationRuleConfig] = Field(default_factory=list, alias="validationRules")
    custom_validation_rules: list[CustomValidationRule] = Field(
        default_factory=list,
        alias="customValidationRules",
    )
    extraction_fields: list[str] = Field(default_factory=list, alias="extractionFields")
    extraction: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    match: list[str] = Field(default_factory=list)
    approval: list[str] = Field(default_factory=list)
    accounting: list[str] = Field(default_factory=list)
    special: list[str] = Field(default_factory=list)
    bundle_mandatory: list[str] = Field(default_factory=list, alias="bundleMandatory")
    bundle_conditional: list[str] = Field(default_factory=list, alias="bundleConditional")
    purchase_bundle_role: PurchaseBundleRole = Field(default="", alias="purchaseBundleRole")
    sample_analysis: DocumentTypeSampleAnalysis | None = Field(
        default=None,
        alias="sampleAnalysis",
    )

    model_config = {"populate_by_name": True}

    @field_validator("matrix_template_code", mode="before")
    @classmethod
    def _normalize_matrix_template_code(cls, value: Any) -> str:
        token = str(value or "").strip().upper()
        if token.startswith("DT-"):
            return token
        return ""

    @field_validator("purchase_bundle_role", mode="before")
    @classmethod
    def _normalize_purchase_bundle_role(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token in {"po", "grn"}:
            return token
        return ""

    @field_validator("playbook_profile", mode="before")
    @classmethod
    def _normalize_playbook_profile(cls, value: Any) -> str:
        from app.schemas.playbook_policy import KNOWN_PLAYBOOK_PROFILES

        token = str(value or "").strip().lower()
        if token in KNOWN_PLAYBOOK_PROFILES:
            return token
        return ""

    @field_validator("match_policy", mode="before")
    @classmethod
    def _normalize_match_policy_field(cls, value: Any) -> MatchPolicy | None:
        if value is None:
            return None
        policy = normalize_match_policy(value)
        return policy

    @field_validator("approval_policy", mode="before")
    @classmethod
    def _normalize_approval_policy_field(cls, value: Any) -> ApprovalPolicy | None:
        if value is None:
            return None
        return normalize_approval_policy(value)

    @field_validator("validation_rules", mode="before")
    @classmethod
    def _normalize_validation_rules(cls, value: Any) -> list[ValidationRuleConfig]:
        return normalize_validation_rules(value)

    @field_validator("custom_validation_rules", mode="before")
    @classmethod
    def _normalize_custom_validation_rules(cls, value: Any) -> list[CustomValidationRule]:
        return normalize_custom_validation_rules(value)

    @field_validator("extraction_fields", mode="before")
    @classmethod
    def _normalize_extraction_fields(cls, value: Any) -> list[str]:
        from app.services.document_type_field_keys import normalize_extraction_field_keys

        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return normalize_extraction_field_keys([str(item) for item in value])

    @field_validator("required_fields", mode="before")
    @classmethod
    def _normalize_required_fields(cls, value: Any) -> list[str]:
        from app.services.document_type_field_keys import normalize_extraction_field_keys

        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return normalize_extraction_field_keys([str(item) for item in value])

    @model_validator(mode="after")
    def _align_compulsory_with_extraction(self) -> DocumentTypeDefinition:
        extraction = list(self.extraction_fields or [])
        required = list(self.required_fields or [])
        if not required and extraction:
            object.__setattr__(self, "required_fields", list(extraction))
            return self
        if not extraction:
            return self
        extraction_set = set(extraction)
        clamped = [key for key in required if key in extraction_set]
        if clamped != required:
            object.__setattr__(self, "required_fields", clamped)
        return self

    @field_validator("bundle_mandatory", mode="before")
    @classmethod
    def _normalize_bundle_mandatory(cls, value: Any) -> list[str]:
        from app.services.document_type_playbook_service import is_dt_code

        if value is None or not isinstance(value, list):
            return []
        seen: set[str] = set()
        normalized: list[str] = []
        for item in value:
            token = str(item).strip().upper()
            if is_dt_code(token) and token not in seen:
                seen.add(token)
                normalized.append(token)
        return normalized

    @field_validator("bundle_conditional", mode="before")
    @classmethod
    def _normalize_bundle_conditional(cls, value: Any) -> list[str]:
        from app.services.document_type_playbook_service import is_dt_code

        if value is None or not isinstance(value, list):
            return []
        seen_codes: set[str] = set()
        normalized: list[str] = []
        for item in value:
            token = str(item).strip()
            if not token:
                continue
            upper = token.upper()
            if is_dt_code(upper):
                if upper not in seen_codes:
                    seen_codes.add(upper)
                    normalized.append(upper)
            elif token not in normalized:
                normalized.append(token)
        return normalized
