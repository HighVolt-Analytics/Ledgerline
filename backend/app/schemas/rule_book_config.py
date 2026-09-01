"""Classification rule book config (email capture, category rules, masters)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.uom_conversion import PurchaseMatchConfig


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
    receivable_account: str | None = None


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


class SalesMatchOn(BaseModel):
    doc_number_contains: str | None = None
    reference_contains: str | None = None
    description_contains: str | None = None
    customer_contains: str | None = None


class SalesRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True
    priority: int = Field(default=100, ge=1)
    match_on: SalesMatchOn = Field(default_factory=SalesMatchOn)
    post_to: PostToAccounts
    matched_count: int = Field(default=0, ge=0)


class TeamExpenseMatchOn(BaseModel):
    description_contains: str | None = None
    merchant_contains: str | None = None
    channel_equals: str | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    department_equals: str | None = None


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


class BankNarrationMatchOn(BaseModel):
    description_contains: str | None = None
    description_pattern: str | None = None


class BankNarrationRule(BaseModel):
    """Bank statement narration → COA category (unmatched lines only)."""

    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True
    priority: int = Field(default=100, ge=1)
    match_on: BankNarrationMatchOn = Field(default_factory=BankNarrationMatchOn)
    post_to: PostToAccounts
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
    approved_by: str = ""
    created_at: datetime | None = None
    total_spend_ytd: float = Field(default=0, ge=0)
    invoice_count: int = Field(default=0, ge=0)
    match_confidence: float = Field(default=0, ge=0, le=100)
    contact_email: str = ""
    contact_phone: str = ""
    confirmation_sent_at: datetime | None = None
    confirmed_at: datetime | None = None
    bank_masked: bool = False


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


class CategoryLimit(BaseModel):
    ledger: str = Field(..., min_length=1)
    cap: float = Field(..., ge=0)


class EmployeeSpendingLimit(BaseModel):
    monthly: float = Field(default=0, ge=0)
    quarterly: float = Field(default=0, ge=0)
    annual: float = Field(default=0, ge=0)
    categories: list[CategoryLimit] = Field(default_factory=list)


# Legacy aliases (reviewer-facing rename; old imports still work)
BudgetCategoryCap = CategoryLimit
EmployeeBudget = EmployeeSpendingLimit


class EmployeeMaster(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    role: str = ""
    email: str = ""
    whatsapp_number: str = ""
    whatsapp_number_2: str = ""
    viber_number: str | None = None
    date_of_joining: str = ""
    department: str = ""
    location: str = ""
    division: str = ""
    supervisor_1: str = ""
    supervisor_2: str = ""
    bank: BankDetails = Field(default_factory=BankDetails)
    spending_limits: EmployeeSpendingLimit = Field(
        default_factory=EmployeeSpendingLimit,
        validation_alias=AliasChoices("spending_limits", "budget"),
        serialization_alias="spending_limits",
    )
    advance_parent_ledger: str = ""
    advance_sub_ledger: str = ""
    ytd_spent: float = Field(default=0, ge=0)
    mtd_spent: float = Field(default=0, ge=0)
    qtd_spent: float = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
    last_claim: str = ""
    status: str = ""
    confirmation_sent_at: datetime | None = None
    confirmed_at: datetime | None = None
    bank_masked: bool = False

    @property
    def budget(self) -> EmployeeSpendingLimit:
        """Deprecated alias for spending_limits."""
        return self.spending_limits


ChartOfAccountType = Literal["Expense", "Asset", "Liability", "Revenue", "Equity"]


SubLedgerOrigin = Literal["party", "manual"]


class SubLedgerEntry(BaseModel):
    """Optional sub-ledger row nested under a main GL account."""

    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    origin: SubLedgerOrigin = "manual"

    @field_validator("code", "name", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ChartOfAccountEntry(BaseModel):
    """GL account row stored per tenant in rule book config."""

    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    type: ChartOfAccountType = "Expense"
    sub_ledgers: list[SubLedgerEntry] = Field(default_factory=list)

    @field_validator("code", "name", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def _unique_sub_ledger_codes_and_names(self) -> ChartOfAccountEntry:
        codes = [item.code.strip().upper() for item in self.sub_ledgers]
        if len(codes) != len(set(codes)):
            raise ValueError(
                f"sub-ledger codes must be unique within account {self.code!r}"
            )
        names = [item.name.strip().lower() for item in self.sub_ledgers]
        if len(names) != len(set(names)):
            raise ValueError(
                f"sub-ledger names must be unique within account {self.code!r}"
            )
        return self


class PostingDefaults(BaseModel):
    """Journal posting accounts shared across all documents."""

    tax_account: str = "Tax Paid"
    payable_account: str = "Accounts Payable"
    receivable_account: str = "Accounts Receivable"
    fallback_account: str = "Suspense Account"
    bank_account: str = "Bank Account"

    @classmethod
    def for_country(cls, country_code: str | None = None) -> "PostingDefaults":
        from app.jurisdiction.packs import jurisdiction_pack_for_country

        pack = jurisdiction_pack_for_country(country_code)
        return cls(
            tax_account=pack.posting_defaults.tax_account,
            payable_account=pack.posting_defaults.payable_account,
            receivable_account=pack.posting_defaults.receivable_account,
            fallback_account=pack.posting_defaults.fallback_account,
            bank_account=pack.posting_defaults.bank_account,
        )


class RemitterBankAccount(BaseModel):
    """This tenant's OWN bank account used to originate batch payment files.

    Deliberately country-agnostic field names -- 'routing_code' holds whatever
    the tenant's country calls it (BSB in AU, sort code in GB, routing number
    in US, IFSC in IN -- see JurisdictionPack.bank_routing_label for the
    display label). Format-specific extras (e.g. an APCA User ID Number for
    AU ABA files) live on BankFileSettings, not here, so this stays reusable
    across every bulk-payment format a tenant's country might need.
    """

    bank_name: str = ""
    account_name: str = ""
    routing_code: str = ""
    account_number: str = ""
    remittance_display_name: str = Field(default="", max_length=32)


class BankFileSettings(BaseModel):
    """Per-tenant configuration for generating batch bank payment files
    (e.g. an AU ABA file) from a set of Scheduled payments.

    'format' is a registry code (see app/services/payments/bank_file_formats)
    such as 'AU_ABA'. Left empty until the tenant explicitly configures one --
    a tenant never gets a batch file format enabled just because their
    country jurisdiction pack lists one as available.
    """

    format: str = ""
    remitter: RemitterBankAccount = Field(default_factory=RemitterBankAccount)
    # AU ABA-specific: "User ID Number" your bank issues you for bulk lodgement.
    aba_user_id_number: str = Field(default="", max_length=6)
    # AU ABA-specific: your bank's registered 3-letter APCA abbreviation
    # (e.g. "CBA", "WBC", "ANZ", "NAB") -- deliberately separate from the
    # free-text remitter.bank_name, which is not safe to truncate into this.
    aba_financial_institution_code: str = Field(default="", max_length=3)
    # Shows in the ABA header's "Description of entries" field (max 12 chars).
    aba_description: str = Field(default="SUPPLIER PAY", max_length=12)


class FxRateSettings(BaseModel):
    """Tenant-owned foreign-exchange rates used to convert invoice/payment
    amounts into this tenant's own books currency (``tenants.currency``) for
    dashboards, reports, and cross-currency aggregates.

    Deliberately NOT a platform-wide hardcoded rate table -- a multi-country
    tenant base sees wildly different currency pairs, and any static snapshot
    goes stale immediately. Each tenant maintains only the pairs they
    actually deal with; unset pairs are treated as "not convertible yet"
    (excluded + flagged) rather than silently guessed as zero-value.

    ``rates`` maps an ISO 4217 code -> how many units of the tenant's own
    books currency one unit of that code is worth right now, e.g. for a
    tenant whose books currency is AUD: {"USD": "1.55", "JPY": "0.0103"}.
    The tenant's own books currency never needs an entry (it is always 1:1).
    """

    rates: dict[str, Decimal] = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @field_validator("rates")
    @classmethod
    def _validate_rates(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        from app.services.shared.iso4217_catalog import is_iso4217_currency

        cleaned: dict[str, Decimal] = {}
        for raw_code, raw_rate in (value or {}).items():
            code = str(raw_code).strip().upper()
            if not is_iso4217_currency(code):
                raise ValueError(f"Unsupported currency code in fx_rate_settings: {raw_code!r}")
            rate = raw_rate if isinstance(raw_rate, Decimal) else Decimal(str(raw_rate))
            if rate <= 0:
                raise ValueError(f"FX rate for {code} must be a positive number")
            cleaned[code] = rate
        return cleaned


TEAM_EXPENSE_KIND_ADVANCE = "advance_requisition"
TEAM_EXPENSE_KIND_CLAIM = "expense_claim"
TEAM_EXPENSE_KIND_DIRECT = "direct_payment"

TeamExpenseKind = Literal[
    "advance_requisition",
    "expense_claim",
    "direct_payment",
]

DEFAULT_TEAM_EXPENSE_KIND: TeamExpenseKind = TEAM_EXPENSE_KIND_CLAIM
DEFAULT_STAFF_ADVANCE_ACCOUNT = "Staff Advance"

# Legacy stored value — normalized to expense_claim.
_LEGACY_AGAINST_ADVANCE = "expense_against_advance"


def normalize_team_expense_kind(value: str | None) -> TeamExpenseKind:
    """Coerce a stored/user kind to a supported value (legacy null → expense claim).

    Historical ``expense_against_advance`` invoices are treated as expense claims.
    """
    cleaned = (value or "").strip().lower()
    if cleaned == _LEGACY_AGAINST_ADVANCE:
        return TEAM_EXPENSE_KIND_CLAIM
    if cleaned in {
        TEAM_EXPENSE_KIND_ADVANCE,
        TEAM_EXPENSE_KIND_CLAIM,
        TEAM_EXPENSE_KIND_DIRECT,
    }:
        return cleaned  # type: ignore[return-value]
    return DEFAULT_TEAM_EXPENSE_KIND


class TeamExpensePostingDefaults(BaseModel):
    """Team Expenses posting accounts — kept out of shared posting defaults.

    Both fields are COA account names chosen by the tenant. Empty means unconfigured;
    journaling fails closed via the control-account gate until the user picks ledgers
    in Rule Book. Greenfield starter tenants set the advance parent explicitly when the
    starter COA is provisioned — do not assume ``DEFAULT_STAFF_ADVANCE_ACCOUNT`` here.
    """

    default_advance_parent_ledger: str = ""
    settlement_account: str = ""

    @field_validator("default_advance_parent_ledger", "settlement_account", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @classmethod
    def for_posting_defaults(cls, posting: PostingDefaults) -> "TeamExpensePostingDefaults":
        """Seed settlement from the jurisdiction bank account; advance parent stays empty."""
        return cls(
            default_advance_parent_ledger="",
            settlement_account=(posting.bank_account or "").strip(),
        )


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


class OrgContextConfig(BaseModel):
    legal_name: str = Field(default="", alias="legalName")
    abn: str = ""
    aliases: list[str] = Field(default_factory=list)
    default_perspective: str = Field(default="buyer", alias="defaultPerspective")
    intake_summary: str = Field(default="", alias="intakeSummary")
    classification_hints: str = Field(default="", alias="classificationHints")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @field_validator("default_perspective", mode="before")
    @classmethod
    def _normalize_perspective(cls, value: object) -> str:
        token = str(value or "buyer").strip().lower()
        if token in {"buyer", "seller", "mixed"}:
            return token
        return "buyer"


def _default_document_ai_provider() -> str:
    from app.config import get_settings

    return get_settings().default_document_ai_provider


class AiClassificationConfig(BaseModel):
    """Gates for auto-routing without human review."""

    document_ai_provider: str = Field(
        default_factory=_default_document_ai_provider,
        alias="documentAiProvider",
        description="azure_di | azure_foundry_vision | gemini_vision | claude_vision",
    )
    auto_route_min_confidence: float = Field(
        default=0.85, ge=0.0, le=1.0, alias="autoRouteMinConfidence"
    )
    ocr_quality_min_text_chars: int | None = Field(
        default=None,
        ge=0,
        alias="ocrQualityMinTextChars",
        description="Minimum OCR text length before classify; defaults to OCR_MIN_TEXT_CHARS env",
    )
    block_sparse_ocr: bool = Field(
        default=True,
        alias="blockSparseOcr",
        description="Reject sparse OCR (mobile photo, skewed scan) before classification",
    )
    min_field_extract_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        alias="minFieldExtractConfidence",
        description="Per-field LLM/OCR confidence floor after extract",
    )
    vendor_few_shot_limit: int = Field(
        default=3,
        ge=0,
        le=10,
        alias="vendorFewShotLimit",
        description="Vendor-specific few-shot examples to prefer before tenant-wide",
    )
    vendor_drift_min_samples: int = Field(
        default=5,
        ge=1,
        alias="vendorDriftMinSamples",
        description="Minimum prior invoices before vendor drift alerts activate",
    )
    vendor_drift_confidence_drop: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        alias="vendorDriftConfidenceDrop",
        description="Alert when LLM confidence drops this far below vendor baseline",
    )
    dt_score_weight_rule: float = Field(
        default=0.45, ge=0.0, le=1.0, alias="dtScoreWeightRule"
    )
    dt_score_weight_fields: float = Field(
        default=0.30, ge=0.0, le=1.0, alias="dtScoreWeightFields"
    )
    dt_score_weight_parse: float = Field(
        default=0.15, ge=0.0, le=1.0, alias="dtScoreWeightParse"
    )
    dt_score_weight_heading: float = Field(
        default=0.10, ge=0.0, le=1.0, alias="dtScoreWeightHeading"
    )
    dt_score_parse_fallback: float = Field(
        default=0.6, ge=0.0, le=1.0, alias="dtScoreParseFallback"
    )
    heading_catalogue_match_min: float = Field(
        default=0.82,
        ge=0.0,
        le=1.0,
        alias="headingCatalogueMatchMin",
        description="Min catalogue/heading alignment score to treat heading as stronger than LLM",
    )
    policy_auto_correct_gap: float = Field(
        default=0.12,
        ge=0.0,
        le=1.0,
        alias="policyAutoCorrectGap",
    )
    policy_review_gap: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        alias="policyReviewGap",
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}


class RuleBookConfigPayload(BaseModel):
    """Org-scoped rule book — single source of truth for classification and posting."""

    schema_version: int = Field(default=1, ge=1)
    document_types: list[DocumentTypeDefinition] = Field(default_factory=list)
    document_classification: DocumentClassificationConfig = Field(
        default_factory=DocumentClassificationConfig
    )
    org_context: OrgContextConfig | None = Field(default=None, alias="orgContext")
    ai_classification: AiClassificationConfig | None = Field(
        default=None, alias="aiClassification"
    )
    email_capture_rules: list[EmailCaptureRule] = Field(default_factory=list)
    purchase_rules: list[PurchaseRule] = Field(default_factory=list)
    sales_rules: list[SalesRule] = Field(default_factory=list)
    expense_rules: list[ExpenseRule] = Field(default_factory=list)
    team_expense_rules: list[TeamExpenseRule] = Field(default_factory=list)
    bank_narration_rules: list[BankNarrationRule] = Field(default_factory=list)
    vendor_masters: list[VendorMaster] = Field(default_factory=list)
    vendor_detection_config: VendorDetectionConfig = Field(
        default_factory=VendorDetectionConfig
    )
    employee_masters: list[EmployeeMaster] = Field(default_factory=list)
    posting_defaults: PostingDefaults = Field(default_factory=PostingDefaults)
    team_expense_posting: TeamExpensePostingDefaults = Field(
        default_factory=TeamExpensePostingDefaults
    )
    chart_of_accounts: list[ChartOfAccountEntry] = Field(default_factory=list)
    document_sets: list[DocumentSetRule] = Field(default_factory=list)
    legacy_cascade: LegacyCascadeConfig = Field(default_factory=LegacyCascadeConfig)
    purchase_match: PurchaseMatchConfig = Field(
        default_factory=PurchaseMatchConfig,
        alias="purchaseMatch",
    )
    bank_file_settings: BankFileSettings = Field(default_factory=BankFileSettings)
    fx_rate_settings: FxRateSettings = Field(default_factory=FxRateSettings)

    model_config = {"populate_by_name": True, "extra": "ignore"}

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

    @model_validator(mode="after")
    def _unique_chart_of_account_codes(self) -> RuleBookConfigPayload:
        codes = [item.code.strip().upper() for item in self.chart_of_accounts]
        if len(codes) != len(set(codes)):
            raise ValueError("chart of account codes must be unique")
        names = [item.name.strip().lower() for item in self.chart_of_accounts]
        if len(names) != len(set(names)):
            raise ValueError("chart of account names must be unique")
        return self


class RuleBookRulesPayload(BaseModel):
    """Rule book rules for PUT/evaluate — masters are managed via dedicated APIs."""

    schema_version: int = Field(default=1, ge=1)
    document_types: list[DocumentTypeDefinition] = Field(default_factory=list)
    document_classification: DocumentClassificationConfig = Field(
        default_factory=DocumentClassificationConfig
    )
    org_context: OrgContextConfig | None = Field(default=None, alias="orgContext")
    ai_classification: AiClassificationConfig | None = Field(
        default=None, alias="aiClassification"
    )
    email_capture_rules: list[EmailCaptureRule] = Field(default_factory=list)
    purchase_rules: list[PurchaseRule] = Field(default_factory=list)
    sales_rules: list[SalesRule] = Field(default_factory=list)
    expense_rules: list[ExpenseRule] = Field(default_factory=list)
    team_expense_rules: list[TeamExpenseRule] = Field(default_factory=list)
    bank_narration_rules: list[BankNarrationRule] = Field(default_factory=list)
    vendor_detection_config: VendorDetectionConfig = Field(
        default_factory=VendorDetectionConfig
    )
    posting_defaults: PostingDefaults = Field(default_factory=PostingDefaults)
    team_expense_posting: TeamExpensePostingDefaults = Field(
        default_factory=TeamExpensePostingDefaults
    )
    document_sets: list[DocumentSetRule] = Field(default_factory=list)
    legacy_cascade: LegacyCascadeConfig = Field(default_factory=LegacyCascadeConfig)
    purchase_match: PurchaseMatchConfig = Field(
        default_factory=PurchaseMatchConfig,
        alias="purchaseMatch",
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}

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
    for key in (
        "purchase_rules",
        "sales_rules",
        "expense_rules",
        "team_expense_rules",
        "bank_narration_rules",
    ):
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
        if not isinstance(row.get("post_to"), dict) and not isinstance(row.get("postTo"), dict):
            row = {
                **row,
                "post_to": {
                    "ledger": "",
                    "sub_ledger": "",
                },
            }
        merged.append(row)
    data["document_types"] = merged
    return data


def _backfill_document_type_klass(data: dict[str, Any]) -> dict[str, Any]:
    """Collapse legacy klass values to Trans-posting / Non-trans, non-posting."""
    from app.services.classification.document_type_klass import (
        derive_posting_from_klass_and_profile,
        normalize_document_type_klass,
    )

    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        klass = normalize_document_type_klass(str(row.get("klass") or ""))
        profile = str(row.get("playbook_profile") or row.get("playbookProfile") or "")
        posting = derive_posting_from_klass_and_profile(
            klass,
            profile,
            existing_posting=str(row.get("posting") or ""),
        )
        merged.append({**row, "klass": klass, "posting": posting})
    data["document_types"] = merged
    return data


def _sync_match_policy_with_playbook(data: dict[str, Any]) -> dict[str, Any]:
    """Align match/approval policies with playbook preset when clearly stale or cross-route."""
    from app.services.classification.playbook_profile_catalog import preset_for_profile

    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    purchase_match_modes = frozenset(
        {"three_way_po_grn", "two_way_po_ses", "two_way_grn_invoice"}
    )
    sales_match_modes = frozenset(
        {"three_way_so_dn", "two_way_so_invoice", "two_way_dn_invoice"}
    )
    sales_profiles = frozenset({"ar_goods", "ar_goods_2way"})
    purchase_profiles = frozenset({"po_goods", "po_services"})

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        profile = str(row.get("playbook_profile") or row.get("playbookProfile") or "").strip().lower()
        if not profile:
            merged.append(row)
            continue
        try:
            preset = preset_for_profile(profile)  # type: ignore[arg-type]
        except Exception:
            merged.append(row)
            continue

        raw_match = row.get("match_policy") or row.get("matchPolicy")
        current_mode = ""
        if isinstance(raw_match, dict):
            current_mode = str(raw_match.get("mode") or "").strip().lower()

        should_sync = not current_mode or current_mode == "none"
        if not should_sync and profile in sales_profiles and current_mode in purchase_match_modes:
            should_sync = True
        if not should_sync and profile in purchase_profiles and current_mode in sales_match_modes:
            should_sync = True

        if should_sync:
            existing_approval = row.get("approval_policy") or row.get("approvalPolicy")
            if not isinstance(existing_approval, dict):
                existing_approval = {}
            merged_approval = {
                **existing_approval,
                "mode": preset.approval_mode,
            }
            row = {
                **row,
                "match_policy": {"mode": preset.match_mode},
                "matchPolicy": {"mode": preset.match_mode},
                "approval_policy": merged_approval,
                "approvalPolicy": merged_approval,
            }
        merged.append(row)
    data["document_types"] = merged
    return data


def _backfill_playbook_profiles(data: dict[str, Any]) -> dict[str, Any]:
    """Persist structural playbook inference once when saving — not at runtime."""
    from app.services.classification.playbook_profile_catalog import (
        default_playbook_profile_for_code,
        infer_playbook_profile_from_definition,
    )

    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        explicit = str(row.get("playbook_profile") or row.get("playbookProfile") or "").strip()
        if explicit:
            merged.append(row)
            continue
        code = str(row.get("code") or "").strip().upper()
        try:
            definition = DocumentTypeDefinition.model_validate(row)
            inferred = default_playbook_profile_for_code(code) if code else "standard_transactional"
            if inferred == "standard_transactional":
                inferred = infer_playbook_profile_from_definition(definition)
        except Exception:
            inferred = default_playbook_profile_for_code(code) if code else "standard_transactional"
        merged.append({**row, "playbook_profile": inferred, "playbookProfile": inferred})
    data["document_types"] = merged
    return data


def _title_matches_shipped_identity(
    org_title: str,
    org_short: str,
    shipped: DocumentTypeDefinition,
) -> bool:
    title = org_title.strip().casefold()
    short = org_short.strip().casefold()
    shipped_title = str(shipped.title or "").strip().casefold()
    shipped_short = str(shipped.short_title or "").strip().casefold()
    if not title and not short:
        return False
    return title in {shipped_title, shipped_short} or short in {shipped_title, shipped_short}


def _matrix_template_title_corruption(
    org_title: str,
    org_short: str,
    matrix_code: str,
    shipped_by_code: dict[str, DocumentTypeDefinition],
) -> bool:
    """True when visible titles belong to a different shipped template than matrix_template_code."""
    shipped = shipped_by_code.get(matrix_code)
    if shipped is None:
        return False
    if _title_matches_shipped_identity(org_title, org_short, shipped):
        return False
    for code, other in shipped_by_code.items():
        if code == matrix_code:
            continue
        if _title_matches_shipped_identity(org_title, org_short, other):
            return True
    return False


def _full_shipped_identity_updates(
    row: dict[str, Any],
    shipped: DocumentTypeDefinition,
    matrix_code: str,
) -> dict[str, Any]:
    """Realign a corrupted org row to the shipped matrix template identity."""
    from app.services.classification.document_type_field_defaults import default_validation_profile
    from app.services.classification.playbook_profile_catalog import default_playbook_profile_for_code

    updates: dict[str, Any] = {}

    shipped_role = (shipped.purchase_bundle_role or "").strip().lower()
    current_role = str(
        row.get("purchase_bundle_role") or row.get("purchaseBundleRole") or ""
    ).strip().lower()
    if shipped_role != current_role:
        updates["purchase_bundle_role"] = shipped_role
        updates["purchaseBundleRole"] = shipped_role

    shipped_playbook = default_playbook_profile_for_code(matrix_code)
    current_playbook = str(
        row.get("playbook_profile") or row.get("playbookProfile") or ""
    ).strip()
    if shipped_playbook and current_playbook != shipped_playbook:
        updates["playbook_profile"] = shipped_playbook
        updates["playbookProfile"] = shipped_playbook

    if shipped.title and str(row.get("title") or "").strip() != shipped.title.strip():
        updates["title"] = shipped.title
    if shipped.short_title and str(
        row.get("short_title") or row.get("shortTitle") or ""
    ).strip() != shipped.short_title.strip():
        updates["short_title"] = shipped.short_title
        updates["shortTitle"] = shipped.short_title

    for key, shipped_val in (
        ("klass", shipped.klass),
        ("posting", shipped.posting),
    ):
        current = str(row.get(key) or "").strip()
        target = str(shipped_val or "").strip()
        if target and current != target:
            updates[key] = target

    shipped_val_profile = default_validation_profile(matrix_code) or (
        shipped.validation_profile or ""
    ).strip()
    current_val_profile = str(
        row.get("validation_profile") or row.get("validationProfile") or ""
    ).strip()
    if shipped_val_profile:
        if current_val_profile != shipped_val_profile:
            updates["validation_profile"] = shipped_val_profile
            updates["validationProfile"] = shipped_val_profile
            if shipped_val_profile == "non_actionable":
                updates["validation_rules"] = []
                updates["validationRules"] = []
    elif (
        current_val_profile == "non_actionable"
        and str(shipped.klass or "").strip().lower() == "transactional"
    ):
        updates["validation_profile"] = ""
        updates["validationProfile"] = ""
        updates["validation_rules"] = []
        updates["validationRules"] = []

    return updates


def _missing_shipped_identity_updates(
    row: dict[str, Any],
    shipped: DocumentTypeDefinition,
    matrix_code: str,
) -> dict[str, Any]:
    """Fill only empty identity fields — preserve org edits on template-linked types."""
    from app.services.classification.document_type_field_defaults import default_validation_profile
    from app.services.classification.playbook_profile_catalog import default_playbook_profile_for_code

    updates: dict[str, Any] = {}

    if not str(row.get("purchase_bundle_role") or row.get("purchaseBundleRole") or "").strip():
        shipped_role = (shipped.purchase_bundle_role or "").strip().lower()
        if shipped_role:
            updates["purchase_bundle_role"] = shipped_role
            updates["purchaseBundleRole"] = shipped_role

    if not str(row.get("playbook_profile") or row.get("playbookProfile") or "").strip():
        shipped_playbook = default_playbook_profile_for_code(matrix_code)
        if shipped_playbook:
            updates["playbook_profile"] = shipped_playbook
            updates["playbookProfile"] = shipped_playbook

    if not str(row.get("title") or "").strip() and shipped.title:
        updates["title"] = shipped.title
    if not str(row.get("short_title") or row.get("shortTitle") or "").strip() and shipped.short_title:
        updates["short_title"] = shipped.short_title
        updates["shortTitle"] = shipped.short_title

    for key, shipped_val in (
        ("klass", shipped.klass),
        ("posting", shipped.posting),
    ):
        if not str(row.get(key) or "").strip() and str(shipped_val or "").strip():
            updates[key] = str(shipped_val).strip()

    if not str(row.get("validation_profile") or row.get("validationProfile") or "").strip():
        shipped_val_profile = default_validation_profile(matrix_code) or (
            shipped.validation_profile or ""
        ).strip()
        if shipped_val_profile:
            updates["validation_profile"] = shipped_val_profile
            updates["validationProfile"] = shipped_val_profile
            if shipped_val_profile == "non_actionable":
                updates["validation_rules"] = []
                updates["validationRules"] = []

    return updates


def _backfill_shipped_document_type_identity(data: dict[str, Any]) -> dict[str, Any]:
    """Align tenant DT rows with shipped catalogue identity when linked to a matrix template.

    Full realign runs only for corrupted rows (titles from a different shipped template).
    Otherwise only missing identity fields are backfilled so org edits survive save/load.
    """
    from app.services.classification.document_type_catalog import (
        load_shipped_default_document_types,
        shipped_matrix_slot_for_org_row,
    )

    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    shipped_by_code = {
        row.code.strip().upper(): row for row in load_shipped_default_document_types()
    }
    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        try:
            definition = DocumentTypeDefinition.model_validate(row)
            matrix_code = shipped_matrix_slot_for_org_row(definition)
        except Exception:
            matrix_code = None
        if not matrix_code:
            merged.append(row)
            continue
        shipped = shipped_by_code.get(matrix_code)
        if shipped is None:
            merged.append(row)
            continue

        org_title = str(row.get("title") or "")
        org_short = str(row.get("short_title") or row.get("shortTitle") or "")
        if not _title_matches_shipped_identity(org_title, org_short, shipped) and not _matrix_template_title_corruption(
            org_title, org_short, matrix_code, shipped_by_code
        ):
            merged.append(row)
            continue

        if _matrix_template_title_corruption(org_title, org_short, matrix_code, shipped_by_code):
            updates = _full_shipped_identity_updates(row, shipped, matrix_code)
        else:
            updates = _missing_shipped_identity_updates(row, shipped, matrix_code)

        merged_row = {**row, **updates} if updates else row
        posting_token = str(
            merged_row.get("posting") or ""
        ).strip().lower()
        if posting_token in {"", "no"}:
            post = merged_row.get("post_to") if isinstance(merged_row.get("post_to"), dict) else None
            if post is None and isinstance(merged_row.get("postTo"), dict):
                post = merged_row.get("postTo")
            if post and str((post or {}).get("ledger") or "").strip():
                merged_row = {
                    **merged_row,
                    "post_to": {**(post or {}), "ledger": "", "sub_ledger": ""},
                    "postTo": {**(post or {}), "ledger": "", "subLedger": ""},
                }

        merged.append(merged_row)
    data["document_types"] = merged
    return data


def _backfill_extraction_fields_from_shipped_defaults(data: dict[str, Any]) -> dict[str, Any]:
    """Union shipped + playbook-recommended extraction keys into tenant document types."""
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.classification.document_type_catalog import shipped_matrix_slot_for_org_row
    from app.services.classification.document_type_field_defaults import default_extraction_fields
    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )
    from app.services.rule_book.extraction_field_config_audit import RECOMMENDED_FIELDS_BY_PLAYBOOK

    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        code = str(row.get("code") or "").strip().upper()
        if not code:
            merged.append(row)
            continue

        current = list(row.get("extraction_fields") or row.get("extractionFields") or [])
        normalized = [str(key).strip() for key in current if str(key or "").strip()]
        seen = {key.lower() for key in normalized}

        def _append(key: str) -> None:
            token = str(key or "").strip()
            if not token:
                return
            lowered = token.lower()
            if lowered in seen:
                return
            normalized.append(token)
            seen.add(lowered)

        # Only seed the full shipped catalogue when the tenant left extraction empty.
        # Always union playbook-recommended keys so gaps (e.g. employee_claim + invoice_no)
        # are filled without wiping intentional field lists.
        seed_shipped = not normalized
        try:
            definition_for_slot = DocumentTypeDefinition.model_validate(row)
            matrix_code = shipped_matrix_slot_for_org_row(definition_for_slot)
        except Exception:
            matrix_code = None
        if seed_shipped and matrix_code:
            for key in default_extraction_fields(matrix_code):
                _append(key)

        try:
            definition = DocumentTypeDefinition.model_validate(row)
            profile = effective_playbook_profile(definition)
            for key in RECOMMENDED_FIELDS_BY_PLAYBOOK.get(profile, ()):
                _append(key)
            for key in definition.required_fields or []:
                _append(str(key))
        except Exception:
            pass

        if normalized != current:
            row = {**row, "extraction_fields": normalized, "extractionFields": normalized}
        merged.append(row)

    data["document_types"] = merged
    return data


def _backfill_validation_rules(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure each document type has the full finance validation rule catalogue."""
    from app.schemas.validation_rule import normalize_validation_rules
    from app.services.classification.document_type_validation_service import effective_validation_profile
    from app.services.rule_book.validation_rule_catalog import merge_configurable_validation_rules

    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        raw_rules = row.get("validation_rules") or row.get("validationRules")
        explicit = normalize_validation_rules(raw_rules)
        if not explicit:
            merged.append(row)
            continue
        try:
            definition = DocumentTypeDefinition.model_validate(row)
            profile = effective_validation_profile(definition)
            code = definition.code
        except Exception:
            profile = str(row.get("validation_profile") or row.get("validationProfile") or "standard")
            code = str(row.get("code") or "").strip().upper()
        rules = merge_configurable_validation_rules(
            explicit,
            validation_profile=profile,
            document_type_code=code,
        )
        merged.append(
            {
                **row,
                "validation_rules": [
                    {"code": item.code, "enabled": item.enabled, "severity": item.severity}
                    for item in rules
                ],
            }
        )
    data["document_types"] = merged
    return data


def _migrate_ai_classification(data: dict[str, Any]) -> dict[str, Any]:
    """Collapse legacy LLM/policy thresholds into a single auto-route gate."""
    raw = data.get("ai_classification") or data.get("aiClassification")
    if not isinstance(raw, dict):
        return data
    if raw.get("auto_route_min_confidence") is not None or raw.get("autoRouteMinConfidence") is not None:
        return data
    llm = raw.get("llm_min_confidence", raw.get("llmMinConfidence"))
    policy = raw.get("policy_min_confidence", raw.get("policyMinConfidence"))
    values = [v for v in (llm, policy) if isinstance(v, (int, float))]
    auto_route = max(values) if values else 0.85
    migrated = dict(data)
    migrated["ai_classification"] = {
        "auto_route_min_confidence": auto_route,
        "document_ai_provider": _default_document_ai_provider(),
    }
    return migrated


def _normalize_ai_classification_provider(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("ai_classification") or data.get("aiClassification")
    if not isinstance(raw, dict):
        return data
    from app.services.extraction.document_ai_provider import DocumentAiProvider, provider_available

    token = str(
        raw.get("document_ai_provider") or raw.get("documentAiProvider") or ""
    ).strip()
    provider = DocumentAiProvider.from_config(
        token or _default_document_ai_provider()
    )
    if not provider_available(provider):
        for candidate in (
            DocumentAiProvider.from_config(_default_document_ai_provider()),
            DocumentAiProvider.CLAUDE_VISION,
            DocumentAiProvider.AZURE_FOUNDRY_VISION,
            DocumentAiProvider.AZURE_DI,
            DocumentAiProvider.GEMINI_VISION,
        ):
            if provider_available(candidate):
                provider = candidate
                break
    merged = dict(data)
    ai = dict(raw)
    ai["document_ai_provider"] = provider.value
    merged["ai_classification"] = ai
    return merged


def _backfill_document_type_post_to(data: dict[str, Any]) -> dict[str, Any]:
    """Suggest / repair Post to ledgers from playbook profile + tenant COA.

    When a transactional DT still points at a ledger removed from the chart
    (e.g. starter ``Operating Expenses`` after a custom COA), remapping to a
    valid playbook default so Rule Book saves are not blocked.
    """
    from app.schemas.rule_book_config import ChartOfAccountEntry
    from app.services.classification.document_type_gl_defaults import (
        default_post_to_ledger,
        resolve_coa_account_name,
    )
    from app.services.classification.document_type_post_to_service import (
        is_control_post_to_ledger,
    )
    from app.services.master_data.chart_of_accounts_service import sub_ledger_exists

    types = data.get("document_types")
    if not isinstance(types, list):
        return data
    coa_raw = data.get("chart_of_accounts") or []
    entries: list[ChartOfAccountEntry] = []
    for row in coa_raw if isinstance(coa_raw, list) else []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        try:
            entries.append(ChartOfAccountEntry.model_validate(row))
        except Exception:
            entries.append(
                ChartOfAccountEntry(
                    code=str(row.get("code") or ""),
                    name=str(row.get("name") or ""),
                    type=row.get("type") or "Expense",
                )
            )

    posting_defaults_raw = data.get("posting_defaults") or data.get("postingDefaults")
    from app.schemas.rule_book_config import PostingDefaults
    from pydantic import ValidationError

    try:
        posting_defaults = (
            PostingDefaults.model_validate(posting_defaults_raw)
            if isinstance(posting_defaults_raw, dict)
            else PostingDefaults()
        )
    except ValidationError:
        posting_defaults = PostingDefaults()

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        posting = str(row.get("posting") or "").strip().lower()
        if posting in {"", "no"}:
            merged.append(row)
            continue
        post = row.get("post_to") if isinstance(row.get("post_to"), dict) else None
        if post is None and isinstance(row.get("postTo"), dict):
            post = row.get("postTo")
        ledger = str((post or {}).get("ledger") or "").strip()
        sub = str(
            (post or {}).get("sub_ledger") or (post or {}).get("subLedger") or ""
        ).strip()
        profile = str(row.get("playbook_profile") or row.get("playbookProfile") or "")
        route_target = str(row.get("route_target") or row.get("routeTarget") or "")

        resolved_ledger = resolve_coa_account_name(ledger, entries) if ledger else ""
        needs_remap = False
        if not ledger and entries:
            needs_remap = True
        elif ledger and not resolved_ledger:
            # Orphaned name (removed from COA) — remapping unless it is clearly a
            # control-account misconfig that validation should still reject.
            if not is_control_post_to_ledger(ledger, posting_defaults=posting_defaults):
                needs_remap = True
        elif ledger and resolved_ledger and resolved_ledger != ledger:
            # Canonicalize casing / fuzzy match to the COA name.
            ledger = resolved_ledger

        if needs_remap and entries:
            remapped = default_post_to_ledger(
                profile, entries, route_target=route_target
            )
            if remapped:
                ledger = remapped
                # Sub-ledger may not belong under the new parent.
                if sub and not sub_ledger_exists(ledger, sub, entries):
                    sub = ""
            elif not resolved_ledger:
                # Leave orphaned ledger for validation to surface a clear error
                # when COA has no suitable fallback account.
                pass

        if ledger or sub or post:
            if sub and ledger and not sub_ledger_exists(ledger, sub, entries):
                sub = ""
            post_payload = {
                **(post or {}),
                "ledger": ledger,
                "sub_ledger": sub,
                "subLedger": sub,
            }
            row = {
                **row,
                "post_to": post_payload,
                "postTo": post_payload,
            }
        merged.append(row)
    data["document_types"] = merged
    return data


def _scrub_non_posting_document_type_post_to(data: dict[str, Any]) -> dict[str, Any]:
    """Clear invoice Post to on non-posting types (supporting roles keep hard posting=No checks)."""
    types = data.get("document_types")
    if not isinstance(types, list):
        return data

    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        posting = str(row.get("posting") or "").strip().lower()
        if posting not in {"", "no"}:
            merged.append(row)
            continue
        post = row.get("post_to") if isinstance(row.get("post_to"), dict) else None
        if post is None and isinstance(row.get("postTo"), dict):
            post = row.get("postTo")
        ledger = str((post or {}).get("ledger") or "").strip()
        sub = str((post or {}).get("sub_ledger") or (post or {}).get("subLedger") or "").strip()
        if not ledger and not sub:
            merged.append(row)
            continue
        post_payload = {
            **(post or {}),
            "ledger": "",
            "sub_ledger": "",
            "subLedger": "",
        }
        merged.append(
            {
                **row,
                "post_to": post_payload,
                "postTo": post_payload,
            }
        )
    data["document_types"] = merged
    return data


def _infer_chart_of_account_type(name: str) -> ChartOfAccountType:
    lower = name.strip().lower()
    if "payable" in lower or "suspense" in lower:
        return "Liability"
    if "gst" in lower or "bank" in lower or "receivable" in lower:
        return "Asset"
    if "revenue" in lower or "income" in lower or "sales" in lower:
        return "Revenue"
    if "equity" in lower or "retained" in lower:
        return "Equity"
    return "Expense"


def validate_rule_book_config_payload(data: dict[str, Any]) -> RuleBookConfigPayload:
    if isinstance(data, dict):
        data = _migrate_root_legacy_fields(dict(data))
        data = _backfill_category_rule_priorities(data)
        data = _backfill_document_types(data)
        data = _backfill_document_type_klass(data)
        data = _merge_document_type_classifiers(data)
        data = _merge_document_type_fields(data)
        from app.services.classification.document_type_recognition_migration import (
            migrate_document_types_recognition,
        )

        data = migrate_document_types_recognition(data)
        data = _backfill_playbook_profiles(data)
        data = _sync_match_policy_with_playbook(data)
        data = _backfill_shipped_document_type_identity(data)
        data = _backfill_extraction_fields_from_shipped_defaults(data)
        data = _backfill_document_type_post_to(data)
        data = _scrub_non_posting_document_type_post_to(data)
        data = _backfill_validation_rules(data)
        data = _migrate_ai_classification(data)
        data = _normalize_ai_classification_provider(data)
    payload = RuleBookConfigPayload.model_validate(data)
    return payload


def validate_rule_book_config_for_save(data: dict[str, Any]) -> RuleBookConfigPayload:
    """Validate and normalize config before persisting (includes Post to checks)."""
    payload = validate_rule_book_config_payload(data)
    from app.services.rule_book.extraction_field_config_audit import (
        log_extraction_field_config_warnings,
    )

    # Audit once on save — never on every request-time validate/load.
    log_extraction_field_config_warnings(payload)
    from app.services.classification.document_type_recognition_migration import (
        sync_classifier_from_recognition,
    )

    # Do NOT merge route compulsory baselines or force due_date here.
    # Stars (required_fields) are tenant-authored: Apply route recommendations /
    # new templates seed them; save must preserve explicit unstars.
    synced_types = [sync_classifier_from_recognition(defn) for defn in payload.document_types]
    payload = payload.model_copy(update={"document_types": synced_types})
    _validate_transactional_document_type_post_to(payload)
    _validate_document_type_bundle_invariants(payload)
    return payload


class RuleBookPostToValidationError(ValueError):
    """Enabled transactional document types must have a valid Post to ledger."""


class RuleBookDocumentTypeInvariantError(ValueError):
    """Document type catalogue violates hard identity / bundle invariants."""


_COMMERCIAL_PLAYBOOKS = frozenset({"po_goods", "ar_goods", "ar_goods_2way", "direct_expense"})
_SUPPORTING_BUNDLE_PURCHASE = frozenset({"po", "grn"})
_SUPPORTING_BUNDLE_SALES = frozenset({"so", "dn"})


def _validate_transactional_document_type_post_to(payload: RuleBookConfigPayload) -> None:
    from app.services.classification.document_type_post_to_service import (
        document_type_requires_post_to,
        has_valid_document_type_post_to,
        is_control_post_to_ledger,
    )

    messages: list[str] = []
    for definition in payload.document_types:
        if not definition.enabled:
            continue
        if not document_type_requires_post_to(definition):
            continue
        if has_valid_document_type_post_to(
            definition,
            payload.chart_of_accounts,
            posting_defaults=payload.posting_defaults,
        ):
            continue
        code = definition.code.strip().upper()
        ledger = (definition.post_to.ledger or "").strip()
        if not ledger:
            messages.append(
                f"{code}: Post to ledger is required for transactional document types."
            )
        elif is_control_post_to_ledger(ledger, posting_defaults=payload.posting_defaults):
            messages.append(
                f"{code}: Post to ledger {ledger!r} cannot be a control account "
                "(AP/AR/bank/cash/suspense) — use an expense or revenue ledger."
            )
        else:
            messages.append(
                f"{code}: Post to ledger {ledger!r} is not in your chart of accounts."
            )
    if messages:
        raise RuleBookPostToValidationError(" ".join(messages))


def _validate_document_type_bundle_invariants(payload: RuleBookConfigPayload) -> None:
    """Hard-fail only structural conflicts; duplicate roles / matrix drift are UI warnings."""
    from app.services.classification.document_type_playbook_profile_service import (
        effective_playbook_profile,
    )

    messages: list[str] = []

    for definition in payload.document_types:
        if not definition.enabled:
            continue
        code = definition.code.strip().upper()
        purchase_role = (definition.purchase_bundle_role or "").strip().lower()
        sales_role = (definition.sales_bundle_role or "").strip().lower()
        profile = effective_playbook_profile(definition)
        posting = (definition.posting or "").strip()
        supporting_role = (
            purchase_role in _SUPPORTING_BUNDLE_PURCHASE
            or sales_role in _SUPPORTING_BUNDLE_SALES
        )

        if supporting_role:
            if profile != "supporting":
                messages.append(
                    f"{code}: bundle role {purchase_role or sales_role} requires playbookProfile=supporting."
                )
            if posting.lower() != "no":
                messages.append(
                    f"{code}: bundle role {purchase_role or sales_role} requires posting=No."
                )

        if profile in _COMMERCIAL_PLAYBOOKS and supporting_role:
            messages.append(
                f"{code}: commercial playbook {profile} cannot also set a PO/GRN/SO/DN bundle role."
            )

    if messages:
        raise RuleBookDocumentTypeInvariantError(" ".join(messages))
