"""Classification rule book config (email capture, category rules, masters)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

from app.schemas.document_type import DocumentTypeDefinition


class RuleCondition(BaseModel):
    type: Literal["condition"] = "condition"
    field: str
    operator: str
    value: str
    case_sensitive: bool | None = None


class RuleConditionGroup(BaseModel):
    type: Literal["group"] = "group"
    operator: Literal["AND", "OR"]
    children: list[RuleConditionNode]


RuleConditionNode = Annotated[
    Union[RuleCondition, RuleConditionGroup],
    Field(discriminator="type"),
]

RuleConditionGroup.model_rebuild()


class EmailCaptureAction(BaseModel):
    save_attachment: bool = True
    route_to: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


class EmailCaptureRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True
    priority: int = Field(..., ge=1)
    mailbox: str = Field(..., min_length=1)
    root: RuleConditionGroup
    action: EmailCaptureAction
    matched_count: int = Field(default=0, ge=0)
    last_matched: str = ""


class PostToAccounts(BaseModel):
    ledger: str = Field(..., min_length=1)
    sub_ledger: str = ""
    tax_account: str | None = None
    payable_account: str | None = None


class PurchaseMatchOn(BaseModel):
    po_prefix: str | None = None
    po_regex: str | None = None
    vendor_contains: str | None = None
    grn_linked_to_po: bool | None = None
    invoice_references_po: bool | None = None


class PurchaseRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True
    priority: int = Field(default=100, ge=1)
    match_on: PurchaseMatchOn = Field(default_factory=PurchaseMatchOn)
    post_to: PostToAccounts
    matched_count: int = Field(default=0, ge=0)


class ExpenseMatchOn(BaseModel):
    doc_number_contains: str | None = None
    reference_contains: str | None = None
    description_contains: str | None = None
    vendor_contains: str | None = None


class ExpenseRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True
    priority: int = Field(default=100, ge=1)
    match_on: ExpenseMatchOn = Field(default_factory=ExpenseMatchOn)
    post_to: PostToAccounts
    matched_count: int = Field(default=0, ge=0)


class TeamExpenseMatchOn(BaseModel):
    description_contains: str | None = None
    merchant_contains: str | None = None
    channel_equals: str | None = None
    amount_min: float | None = None
    amount_max: float | None = None


class TeamExpensePolicy(BaseModel):
    require_receipt: bool = True
    receipt_threshold: float = 0
    auto_approve_below: float = 0


class TeamExpenseRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True
    priority: int = Field(default=100, ge=1)
    match_on: TeamExpenseMatchOn = Field(default_factory=TeamExpenseMatchOn)
    post_to: PostToAccounts
    policy: TeamExpensePolicy = Field(default_factory=TeamExpensePolicy)
    matched_count: int = Field(default=0, ge=0)


class BillingAddress(BaseModel):
    street: str = ""
    suburb: str = ""
    postcode: str = ""
    country: str = ""


class BankDetails(BaseModel):
    bsb: str | None = None
    account_number: str = ""
    account_name: str = ""
    bank_name: str = ""
    swift: str | None = None
    iban: str | None = None


class VendorMaster(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    abn: str = ""
    billing_address: BillingAddress = Field(default_factory=BillingAddress)
    bank: BankDetails = Field(default_factory=BankDetails)
    default_ledger: str = ""
    default_sub_ledger: str = ""
    payment_terms: str = ""
    status: str = ""
    registered_on: str = ""
    total_spend_ytd: float = Field(default=0, ge=0)
    invoice_count: int = Field(default=0, ge=0)
    match_confidence: float = Field(default=0, ge=0, le=100)


class VendorDetectionWeights(BaseModel):
    name: int = Field(default=30, ge=0, le=100)
    abn: int = Field(default=40, ge=0, le=100)
    bank: int = Field(default=20, ge=0, le=100)
    address: int = Field(default=10, ge=0, le=100)


class VendorDetectionConfig(BaseModel):
    weights: VendorDetectionWeights = Field(default_factory=VendorDetectionWeights)
    threshold: int = Field(default=70, ge=0, le=100)
    expense_vendor_hold_above: float = Field(
        default=500,
        ge=0,
        description="Expenses Management: hold unknown vendors only above this amount (AUD)",
    )


class BudgetCategoryCap(BaseModel):
    ledger: str = Field(..., min_length=1)
    cap: float = Field(..., ge=0)


class EmployeeBudget(BaseModel):
    monthly: float = Field(default=0, ge=0)
    quarterly: float = Field(default=0, ge=0)
    annual: float = Field(default=0, ge=0)
    categories: list[BudgetCategoryCap] = Field(default_factory=list)


class EmployeeMaster(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    role: str = ""
    email: str = ""
    whatsapp_number: str = ""
    viber_number: str | None = None
    bank: BankDetails = Field(default_factory=BankDetails)
    budget: EmployeeBudget = Field(default_factory=EmployeeBudget)
    ytd_spent: float = Field(default=0, ge=0)
    mtd_spent: float = Field(default=0, ge=0)
    qtd_spent: float = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
    last_claim: str = ""
    status: str = ""


class PostingDefaults(BaseModel):
    """Journal posting accounts shared across all documents."""

    tax_account: str = "GST Paid"
    payable_account: str = "Accounts Payable"
    fallback_account: str = "Suspense Account"


class DocumentSetRule(BaseModel):
    """Vault document set grouping (pattern match on PO / invoice number)."""

    id: str
    pattern: str
    set_name: str
    isolated: bool = False


class LegacyDocCode(BaseModel):
    id: str = ""
    pattern: str = Field(..., min_length=1)
    account: str = Field(..., min_length=1)
    isolated: bool = False


class LegacyCascadeConfig(BaseModel):
    """v3 po_codes → doc_codes → vendor → keyword backstop (architecture §9.5)."""

    enabled: bool = True
    priority_order: list[str] = Field(
        default_factory=lambda: ["po_code", "doc_code", "vendor", "keyword"]
    )
    po_codes: dict[str, str] = Field(default_factory=dict)
    po_code_isolated: dict[str, bool] = Field(default_factory=dict)
    doc_codes: list[LegacyDocCode] = Field(default_factory=list)
    vendors: dict[str, str] = Field(default_factory=dict)
    vendor_isolated: dict[str, bool] = Field(default_factory=dict)
    keywords: dict[str, str] = Field(default_factory=dict)
    keyword_isolated: dict[str, bool] = Field(default_factory=dict)


def _migrate_root_legacy_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Coalesce pre-v4 root keys (po_codes, keywords, …) into legacy_cascade."""
    if "legacy_cascade" in data or "po_codes" not in data:
        return data
    legacy: dict[str, Any] = {
        "enabled": True,
        "priority_order": data.pop(
            "priority_order",
            ["po_code", "doc_code", "vendor", "keyword"],
        ),
        "po_codes": data.pop("po_codes", {}),
        "po_code_isolated": data.pop("po_code_isolated", {}),
        "doc_codes": data.pop("doc_codes", []),
        "vendors": data.pop("vendors", {}),
        "vendor_isolated": data.pop("vendor_isolated", {}),
        "keywords": data.pop("keywords", {}),
        "keyword_isolated": data.pop("keyword_isolated", {}),
    }
    data["legacy_cascade"] = legacy
    return data


class DocumentClassificationConfig(BaseModel):
    """Org-level fallback when no DT classifier matches."""

    unclassified_document_type_code: str = Field(default="", max_length=16)
    unclassified_min_confidence: float = Field(default=0.45, ge=0.0, le=1.0)


class RuleBookConfigPayload(BaseModel):
    """Org-scoped rule book — single source of truth for classification and posting."""

    schema_version: int = Field(default=1, ge=1)
    document_types: list[DocumentTypeDefinition] = Field(default_factory=list)
    document_classification: DocumentClassificationConfig = Field(
        default_factory=DocumentClassificationConfig
    )
    email_capture_rules: list[EmailCaptureRule] = Field(default_factory=list)
    purchase_rules: list[PurchaseRule] = Field(default_factory=list)
    expense_rules: list[ExpenseRule] = Field(default_factory=list)
    team_expense_rules: list[TeamExpenseRule] = Field(default_factory=list)
    vendor_masters: list[VendorMaster] = Field(default_factory=list)
    vendor_detection_config: VendorDetectionConfig = Field(
        default_factory=VendorDetectionConfig
    )
    employee_masters: list[EmployeeMaster] = Field(default_factory=list)
    posting_defaults: PostingDefaults = Field(default_factory=PostingDefaults)
    document_sets: list[DocumentSetRule] = Field(default_factory=list)
    legacy_cascade: LegacyCascadeConfig = Field(default_factory=LegacyCascadeConfig)

    @model_validator(mode="after")
    def _unique_document_type_codes(self) -> RuleBookConfigPayload:
        codes = [item.code.strip().upper() for item in self.document_types]
        if len(codes) != len(set(codes)):
            raise ValueError("document type codes must be unique")
        return self

    @model_validator(mode="after")
    def _sanitize_unclassified_document_type(self) -> RuleBookConfigPayload:
        configured = self.document_classification.unclassified_document_type_code.strip().upper()
        if not configured:
            return self
        catalogue = {item.code.strip().upper() for item in self.document_types}
        if configured in catalogue:
            return self
        self.document_classification = self.document_classification.model_copy(
            update={"unclassified_document_type_code": ""}
        )
        return self


class RuleBookRulesPayload(BaseModel):
    """Rule book rules for PUT/evaluate — masters are managed via dedicated APIs."""

    schema_version: int = Field(default=1, ge=1)
    document_types: list[DocumentTypeDefinition] = Field(default_factory=list)
    document_classification: DocumentClassificationConfig = Field(
        default_factory=DocumentClassificationConfig
    )
    email_capture_rules: list[EmailCaptureRule] = Field(default_factory=list)
    purchase_rules: list[PurchaseRule] = Field(default_factory=list)
    expense_rules: list[ExpenseRule] = Field(default_factory=list)
    team_expense_rules: list[TeamExpenseRule] = Field(default_factory=list)
    vendor_detection_config: VendorDetectionConfig = Field(
        default_factory=VendorDetectionConfig
    )
    posting_defaults: PostingDefaults = Field(default_factory=PostingDefaults)
    document_sets: list[DocumentSetRule] = Field(default_factory=list)
    legacy_cascade: LegacyCascadeConfig = Field(default_factory=LegacyCascadeConfig)

    @model_validator(mode="after")
    def _unique_document_type_codes(self) -> RuleBookRulesPayload:
        codes = [item.code.strip().upper() for item in self.document_types]
        if len(codes) != len(set(codes)):
            raise ValueError("document type codes must be unique")
        return self

    @model_validator(mode="after")
    def _sanitize_unclassified_document_type(self) -> RuleBookRulesPayload:
        configured = self.document_classification.unclassified_document_type_code.strip().upper()
        if not configured:
            return self
        catalogue = {item.code.strip().upper() for item in self.document_types}
        if configured in catalogue:
            return self
        self.document_classification = self.document_classification.model_copy(
            update={"unclassified_document_type_code": ""}
        )
        return self


def _backfill_category_rule_priorities(data: dict[str, Any]) -> dict[str, Any]:
    """Assign priority 100, 110, … when missing (architecture §2.2)."""
    for key in ("purchase_rules", "expense_rules", "team_expense_rules"):
        rules = data.get(key)
        if not isinstance(rules, list):
            continue
        for index, rule in enumerate(rules):
            if isinstance(rule, dict) and "priority" not in rule:
                rule["priority"] = 100 + index * 10
    return data


def _backfill_document_types(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure document_types exists; orgs start empty until users define cards."""
    existing = data.get("document_types")
    if isinstance(existing, list):
        return data
    data["document_types"] = []
    return data


def _count_classifier_conditions(node: dict[str, Any]) -> int:
    if node.get("type") == "condition":
        return 1
    if node.get("type") == "group":
        return sum(
            _count_classifier_conditions(child)
            for child in node.get("children") or []
            if isinstance(child, dict)
        )
    return 0


def _collect_document_text_signatures(node: dict[str, Any]) -> tuple[str, ...]:
    if node.get("type") == "condition" and node.get("field") == "document_text":
        operator = str(node.get("operator") or "")
        value = str(node.get("value") or "")
        return (f"{operator}:{value}",)
    if node.get("type") == "group":
        parts: list[str] = []
        for child in node.get("children") or []:
            if isinstance(child, dict):
                parts.extend(_collect_document_text_signatures(child))
        return tuple(parts)
    return ()


def _merge_document_type_classifiers(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure each org document type has a classifier object — never inject shipped templates."""
    types = data.get("document_types")
    if not isinstance(types, list):
        return data
    empty_classifier = {
        "enabled": False,
        "priority": 100,
        "confidence": 0.85,
        "root": {"type": "group", "operator": "AND", "children": []},
    }
    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        if not isinstance(row.get("classifier"), dict):
            row = {**row, "classifier": empty_classifier}
        merged.append(row)
    data["document_types"] = merged
    return data


def _merge_document_type_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize org document type rows without injecting shipped per-code defaults."""
    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        updates: dict[str, Any] = {}
        if row.get("min_route_confidence") is None and row.get("minRouteConfidence") is None:
            updates["min_route_confidence"] = 0.65
        for legacy_key in ("extraction", "checks", "match", "approval", "accounting", "special"):
            if row.get(legacy_key):
                updates[legacy_key] = []
        if updates:
            row = {**row, **updates}
        merged.append(row)
    data["document_types"] = merged
    return data


def validate_rule_book_config_payload(data: dict[str, Any]) -> RuleBookConfigPayload:
    if isinstance(data, dict):
        data = _migrate_root_legacy_fields(dict(data))
        data = _backfill_category_rule_priorities(data)
        data = _backfill_document_types(data)
        data = _merge_document_type_classifiers(data)
        data = _merge_document_type_fields(data)
    return RuleBookConfigPayload.model_validate(data)
