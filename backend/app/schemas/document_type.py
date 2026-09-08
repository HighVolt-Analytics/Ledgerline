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


class DocumentTypePostTo(BaseModel):
    """GL posting targets per document type; ledger may be empty until configured."""

    ledger: str = ""
    sub_ledger: str = Field(default="", alias="subLedger")
    tax_account: str | None = Field(default=None, alias="taxAccount")
    payable_account: str | None = Field(default=None, alias="payableAccount")
    receivable_account: str | None = Field(default=None, alias="receivableAccount")

    model_config = {"populate_by_name": True}

    def as_post_to_accounts(self):
        from app.schemas.rule_book_config import PostToAccounts

        cleaned = (self.ledger or "").strip()
        if not cleaned:
            return None
        return PostToAccounts(
            ledger=cleaned,
            sub_ledger=(self.sub_ledger or "").strip(),
            tax_account=self.tax_account,
            payable_account=self.payable_account,
            receivable_account=self.receivable_account,
        )


DocumentTypeRouteTarget = Literal[
    "Purchase Management",
    "Sales Management",
    "Expenses Management",
    "Team Expenses",
    "Vault",
]

PurchaseBundleRole = Literal["", "po", "grn"]
SalesBundleRole = Literal["", "so", "dn"]
# Empty means auto: expense claim (unless DT pins advance requisition).
DocumentTypeTeamExpenseKind = Literal[
    "",
    "advance_requisition",
    "expense_claim",
    "direct_payment",
]
TEAM_EXPENSE_KIND_CHOICES = frozenset(
    {"advance_requisition", "expense_claim", "direct_payment"}
)
RecognitionMode = Literal["signals", "prompt"]
CounterpartySource = Literal["letterhead", "consignee", "applicant", "bill_to"]
CounterpartyType = Literal["vendor", "customer"]
COUNTERPARTY_TYPE_CHOICES = frozenset({"vendor", "customer"})


def default_counterparty_type_for_route(route_target: str | None) -> CounterpartyType:
    route = (route_target or "").strip()
    if route == "Sales Management":
        return "customer"
    return "vendor"


def resolved_counterparty_type(
    definition: DocumentTypeDefinition | None,
    *,
    route_target: str | None = None,
) -> CounterpartyType:
    if definition is not None:
        token = (definition.counterparty_type or "").strip().lower()
        if token in COUNTERPARTY_TYPE_CHOICES:
            return token  # type: ignore[return-value]
        route_target = route_target or definition.route_target
    return default_counterparty_type_for_route(route_target)


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
        from app.services.rule_book.rule_engine import sanitize_condition_group

        validated = RuleConditionGroup.model_validate(value).model_dump()
        return sanitize_condition_group(validated)


class DocumentTypeDefinition(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    title: str
    short_title: str = Field(alias="shortTitle")
    klass: str
    posting: str
    recognition_mode: RecognitionMode = Field(default="signals", alias="recognitionMode")
    recognition_signals: list[str] = Field(default_factory=list, alias="recognitionSignals")
    llm_prompt: str = Field(default="", alias="llmPrompt")
    route_target: DocumentTypeRouteTarget = Field(
        default="Vault",
        alias="routeTarget",
    )
    counterparty_type: CounterpartyType = Field(
        default="vendor",
        alias="counterpartyType",
        description="QBO/Xero party kind for the extracted name: vendor or customer.",
    )
    enabled: bool = True
    classifier: DocumentTypeClassifier = Field(default_factory=DocumentTypeClassifier)
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
    sales_bundle_role: SalesBundleRole = Field(default="", alias="salesBundleRole")
    counterparty_source: CounterpartySource = Field(
        default="letterhead",
        alias="counterpartySource",
    )
    team_expense_kind: DocumentTypeTeamExpenseKind = Field(
        default="",
        alias="teamExpenseKind",
        description="Claim kind stamped on Team Expenses documents; empty defaults to expense claim.",
    )
    budget_control: bool = Field(
        default=False,
        alias="budgetControl",
        description="When true, enforce employee-level budget availability for this document type.",
    )
    advance_control: bool = Field(
        default=False,
        alias="advanceControl",
        description="When true, surface employee Staff Advance float for this document type.",
    )
    sample_analysis: DocumentTypeSampleAnalysis | None = Field(
        default=None,
        alias="sampleAnalysis",
    )
    post_to: DocumentTypePostTo = Field(default_factory=DocumentTypePostTo, alias="postTo")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _inject_counterparty_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        existing = data.get("counterparty_type", data.get("counterpartyType"))
        token = str(existing or "").strip().lower()
        if token in COUNTERPARTY_TYPE_CHOICES:
            patched = dict(data)
            patched["counterparty_type"] = token
            return patched
        route = data.get("route_target", data.get("routeTarget"))
        patched = dict(data)
        patched["counterparty_type"] = default_counterparty_type_for_route(str(route or ""))
        return patched

    @field_validator("klass", mode="before")
    @classmethod
    def _normalize_klass(cls, value: Any) -> str:
        from app.services.classification.document_type_klass import normalize_document_type_klass

        return normalize_document_type_klass(str(value or ""))

    @model_validator(mode="after")
    def _derive_posting_from_klass(self) -> DocumentTypeDefinition:
        from app.services.classification.document_type_klass import derive_posting_from_klass_and_profile

        posting = derive_posting_from_klass_and_profile(
            self.klass,
            self.playbook_profile,
            existing_posting=self.posting,
        )
        if posting != self.posting:
            object.__setattr__(self, "posting", posting)
        return self

    @model_validator(mode="after")
    def _reconcile_team_expense_kind_with_title(self) -> DocumentTypeDefinition:
        """Heal swapped claim/advance pins using title wording (Team Expenses only)."""
        route = (self.route_target or "").strip()
        if route != "Team Expenses":
            return self
        from app.services.purchase.team_expense_kind_service import (
            reconcile_team_expense_kind_for_document_type,
        )

        reconciled = reconcile_team_expense_kind_for_document_type(
            title=self.title,
            short_title=self.short_title,
            configured=self.team_expense_kind,
        )
        if reconciled != (self.team_expense_kind or ""):
            object.__setattr__(self, "team_expense_kind", reconciled)
        return self

    @field_validator("recognition_mode", mode="before")
    @classmethod
    def _normalize_recognition_mode(cls, value: Any) -> str:
        token = str(value or "signals").strip().lower()
        return token if token in {"signals", "prompt"} else "signals"

    @field_validator("team_expense_kind", mode="before")
    @classmethod
    def _normalize_team_expense_kind(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        return token if token in TEAM_EXPENSE_KIND_CHOICES else ""

    @field_validator("recognition_signals", mode="before")
    @classmethod
    def _normalize_recognition_signals(cls, value: Any) -> list[str]:
        from app.services.classification.recognition_signal_registry import SIGNAL_CONDITIONS

        if value is None or not isinstance(value, list):
            return []
        seen: set[str] = set()
        normalized: list[str] = []
        for item in value:
            token = str(item).strip()
            if token in SIGNAL_CONDITIONS and token not in seen:
                seen.add(token)
                normalized.append(token)
        return normalized

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

    @field_validator("sales_bundle_role", mode="before")
    @classmethod
    def _normalize_sales_bundle_role(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token in {"so", "dn"}:
            return token
        return ""

    @field_validator("counterparty_source", mode="before")
    @classmethod
    def _normalize_counterparty_source(cls, value: Any) -> str:
        token = str(value or "letterhead").strip().lower()
        if token in {"letterhead", "consignee", "applicant", "bill_to"}:
            return token
        return "letterhead"

    @field_validator("counterparty_type", mode="before")
    @classmethod
    def _normalize_counterparty_type(cls, value: Any, info) -> str:
        token = str(value or "").strip().lower()
        if token in COUNTERPARTY_TYPE_CHOICES:
            return token
        route = ""
        if info.data:
            route = str(info.data.get("route_target") or "")
        return default_counterparty_type_for_route(route)

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
        from app.services.classification.document_type_field_keys import normalize_extraction_field_keys

        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return normalize_extraction_field_keys([str(item) for item in value])

    @field_validator("required_fields", mode="before")
    @classmethod
    def _normalize_required_fields(cls, value: Any) -> list[str]:
        from app.services.classification.document_type_field_keys import normalize_extraction_field_keys

        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return normalize_extraction_field_keys([str(item) for item in value])

    @model_validator(mode="after")
    def _align_compulsory_with_extraction(self) -> DocumentTypeDefinition:
        extraction = list(self.extraction_fields or [])
        required = list(self.required_fields or [])
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
        from app.services.classification.document_type_playbook_service import is_dt_code

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
        from app.services.classification.document_type_playbook_service import is_dt_code

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
