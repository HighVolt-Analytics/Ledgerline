"""Bank feed API schemas (user-facing copy avoids internal jargon)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.bank_feeds.currency_validation import validate_bank_account_currency


class BankAccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    currency: str = Field(..., min_length=3, max_length=3)
    account_number: str = Field(..., min_length=1, max_length=64)
    account_mask: str | None = Field(default=None, max_length=32)
    coa_account_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="COA ledger name from Chart of Accounts.",
    )

    @field_validator("currency")
    @classmethod
    def currency_must_be_supported(cls, value: str) -> str:
        return validate_bank_account_currency(value)

    @field_validator("account_number")
    @classmethod
    def account_number_must_be_present(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Account number is required")
        return cleaned


class BankAccountUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    currency: str = Field(..., min_length=3, max_length=3)
    account_number: str = Field(..., min_length=1, max_length=64)
    account_mask: str | None = Field(default=None, max_length=32)
    coa_account_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("currency")
    @classmethod
    def currency_must_be_supported(cls, value: str) -> str:
        return validate_bank_account_currency(value)

    @field_validator("account_number")
    @classmethod
    def account_number_must_be_present(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Account number is required")
        return cleaned


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    currency: str
    account_number: str | None = None
    account_mask: str | None = None
    coa_account_code: str
    coa_account_name: str
    connection_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class PendingBankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    detected_name: str | None = None
    detected_account_number: str | None = None
    detected_currency: str | None = None
    filename: str | None = None
    file_sha256: str
    source: str
    extracted_count: int = 0
    confidence: float = 0
    parse_meta: dict[str, Any] | list | None = None
    status: str
    promoted_bank_account_id: int | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class PendingBankAccountPromote(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    account_number: str = Field(..., min_length=1, max_length=64)
    currency: str = Field(..., min_length=3, max_length=3)
    coa_account_name: str = Field(..., min_length=1, max_length=255)
    bank_account_id: int | None = Field(
        default=None,
        description="Optional existing bank account to link/import into instead of creating.",
    )

    @field_validator("currency")
    @classmethod
    def currency_must_be_supported(cls, value: str) -> str:
        return validate_bank_account_currency(value)

    @field_validator("account_number")
    @classmethod
    def account_number_must_be_present(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Account number is required")
        return cleaned


class PendingBankPromoteResponse(BaseModel):
    account: BankAccountResponse
    import_result: BankFeedImportResponse | None = None
    pending: PendingBankAccountResponse


class UnassignedStatementIngestResponse(BaseModel):
    """Result of uploading a statement without selecting a bank account."""

    disposition: Literal["pending", "auto_imported"]
    match_reason: str | None = None
    pending: PendingBankAccountResponse | None = None
    account: BankAccountResponse | None = None
    import_result: BankFeedImportResponse | None = None


class BankFeedImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_account_id: int
    source: str
    filename: str | None = None
    file_sha256: str
    status: str
    row_count: int
    accepted_count: int
    duplicate_count: int
    error_count: int
    categorized_count: int = 0
    extracted_count: int = 0
    error_report: dict[str, Any] | list | None = None
    actor_user_id: int | None = None
    imported_at: datetime
    reused_existing: bool = False


class BankTransactionMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_transaction_id: int
    matched_type: str
    matched_id: int
    allocated_amount: float
    match_confidence: float
    match_method: str
    match_reasons: dict[str, Any] | None = None
    matched_by: str | None = None
    matched_at: datetime
    unmatched_at: datetime | None = None
    unmatch_reason: str | None = None
    # User-facing counterparty / invoice labels (never show matched_id alone in UI).
    party_name: str | None = None
    invoice_no: str | None = None
    display_label: str | None = None


class BankMatchTargetResponse(BaseModel):
    """Payment or collection row for the manual-match picker (no raw-ID UX)."""

    id: int
    matched_type: Literal["payment", "collection"]
    party_name: str | None = None
    invoice_no: str | None = None
    amount: float
    currency: str
    status: str
    display_label: str


class BankTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_account_id: int
    import_id: int | None = None
    txn_date: date
    posted_date: date | None = None
    description: str
    amount: float
    currency: str
    money_flow: Literal["in", "out"]
    balance: float | None = None
    reference: str | None = None
    match_status: str
    category_coa: str | None = None
    category_source: Literal["rule", "manual"] | None = None
    category_rule_name: str | None = None
    category_matched_snippet: str | None = None
    possible_duplicate_of: list[int] | None = None
    posted_journal_batch_id: int | None = None
    created_at: datetime
    updated_at: datetime
    matches: list[BankTransactionMatchResponse] = Field(default_factory=list)


class BankCreatePartyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class BankCreateRequest(BaseModel):
    party_type: Literal["vendor", "customer"]
    party_id: int | None = Field(default=None, ge=1)
    create_party: BankCreatePartyRequest | None = None
    ledger: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=2000)
    tax_rate_percent: float = Field(..., ge=0, le=100)

    @model_validator(mode="after")
    def exactly_one_party_source(self) -> "BankCreateRequest":
        if (self.party_id is None) == (self.create_party is None):
            raise ValueError("Provide exactly one of party_id or create_party")
        return self


class BankTransactionListResponse(BaseModel):
    items: list[BankTransactionResponse]


class ManualMatchRequest(BaseModel):
    matched_type: Literal["payment", "collection"]
    matched_id: int = Field(..., ge=1)
    allocated_amount: float | None = Field(
        default=None,
        gt=0,
        description="Defaults to min(bank line amount, remaining unallocated).",
    )


class SetCategoryRequest(BaseModel):
    category_coa: str | None = Field(
        default=None,
        max_length=255,
        description="Display COA label; null clears. Or set ledger/sub_ledger.",
    )
    ledger: str | None = Field(default=None, max_length=255)
    sub_ledger: str | None = Field(default=None, max_length=255)


class CategorizeRunItemResponse(BaseModel):
    transaction_id: int
    categorized: bool
    category_coa: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None


class CategorizeRunResponse(BaseModel):
    items: list[CategorizeRunItemResponse]
    categorized_count: int


class UnmatchRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class ExcludeTransactionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class MatchRunItemResponse(BaseModel):
    transaction_id: int
    status: str
    matches_written: int
    auto_matched: bool
    tie_demoted: bool


class MatchRunResponse(BaseModel):
    items: list[MatchRunItemResponse]


class BankFeedImportListResponse(BaseModel):
    items: list[BankFeedImportResponse]


class BankTransferRequest(BaseModel):
    to_bank_account_id: int = Field(..., ge=1)
    description: str = Field(..., min_length=1, max_length=2000)


class BankTransactionNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_transaction_id: int
    body: str
    author_user_id: int | None = None
    created_at: datetime


class CreateBankTransactionNoteRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class UnsettledSettlementResponse(BaseModel):
    entity_type: Literal["payment", "collection"]
    entity_id: int
    invoice_id: int
    invoice_no: str | None = None
    party_name: str | None = None
    amount: Decimal
    currency: str
    settled_date: date
    days_since_settled: int
    has_suggested_bank_match: bool
    allocated_bank_amount: Decimal
    gross_amount: Decimal | None = None
    grace_days: int


class UnsettledSettlementListResponse(BaseModel):
    items: list[UnsettledSettlementResponse]
    grace_days: int
    lookback_months: int = 12


class UnsettledSettlementCountResponse(BaseModel):
    count: int
    grace_days: int
