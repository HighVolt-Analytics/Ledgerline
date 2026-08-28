"""Master data API schemas (vendor/employee masters, pending vendors)."""

from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.schemas.rule_book_config import (
    BankDetails,
    BillingAddress,
    EmployeeBudget,
    EmployeeMaster,
    EmployeeSpendingLimit,
    VendorMaster,
)


class VendorMasterCreate(BaseModel):
    master_id: str | None = Field(None, min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    abn: str = ""
    billing_address: BillingAddress = Field(default_factory=BillingAddress)
    bank: BankDetails = Field(default_factory=BankDetails)
    default_ledger: str = ""
    default_sub_ledger: str = ""
    payment_terms: str = ""
    status: str = "Pending registration"
    registered_on: str = ""
    approved_by: str = ""
    total_spend_ytd: float = Field(default=0, ge=0)
    invoice_count: int = Field(default=0, ge=0)
    match_confidence: float = Field(default=0, ge=0, le=100)
    contact_email: str = ""
    contact_phone: str = ""


class VendorMasterUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    aliases: list[str] | None = None
    abn: str | None = None
    billing_address: BillingAddress | None = None
    bank: BankDetails | None = None
    default_ledger: str | None = None
    default_sub_ledger: str | None = None
    payment_terms: str | None = None
    status: str | None = None
    registered_on: str | None = None
    total_spend_ytd: float | None = Field(None, ge=0)
    invoice_count: int | None = Field(None, ge=0)
    match_confidence: float | None = Field(None, ge=0, le=100)
    contact_email: str | None = None
    contact_phone: str | None = None


class VendorMasterResponse(VendorMaster):
    """Public vendor master shape (id = master_id)."""

    db_id: int


class EmployeeMasterCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    master_id: str | None = Field(None, min_length=1, max_length=100)
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
    )
    advance_parent_ledger: str = ""
    ytd_spent: float = Field(default=0, ge=0)
    mtd_spent: float = Field(default=0, ge=0)
    qtd_spent: float = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
    last_claim: str = ""
    status: str = "Pending verification"

    @property
    def budget(self) -> EmployeeSpendingLimit:
        return self.spending_limits


class EmployeeMasterUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(None, min_length=1, max_length=255)
    role: str | None = None
    email: str | None = None
    whatsapp_number: str | None = None
    whatsapp_number_2: str | None = None
    viber_number: str | None = None
    date_of_joining: str | None = None
    department: str | None = None
    location: str | None = None
    division: str | None = None
    supervisor_1: str | None = None
    supervisor_2: str | None = None
    bank: BankDetails | None = None
    spending_limits: EmployeeSpendingLimit | None = Field(
        default=None,
        validation_alias=AliasChoices("spending_limits", "budget"),
    )
    advance_parent_ledger: str | None = None
    ytd_spent: float | None = Field(None, ge=0)
    mtd_spent: float | None = Field(None, ge=0)
    qtd_spent: float | None = Field(None, ge=0)
    claim_count: int | None = Field(None, ge=0)
    last_claim: str | None = None
    status: str | None = None

    @property
    def budget(self) -> EmployeeSpendingLimit | None:
        return self.spending_limits


class EmployeeMasterResponse(EmployeeMaster):
    db_id: int
    advance_balance: float = Field(
        default=0,
        ge=0,
        description="Live Staff Advance child balance from journals; not persisted.",
    )


class EmployeeImportRowErrorResponse(BaseModel):
    row_number: int
    email: str | None = None
    message: str


class EmployeeImportRowPreviewResponse(BaseModel):
    row_number: int
    email: str
    name: str | None = None
    action: str
    detail: str


class EmployeeImportResultResponse(BaseModel):
    mode: str
    dry_run: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[EmployeeImportRowErrorResponse] = Field(default_factory=list)
    previews: list[EmployeeImportRowPreviewResponse] = Field(default_factory=list)


class PendingVendorCreate(BaseModel):
    detected_name: str = Field(..., min_length=1, max_length=255)
    detected_abn: str | None = Field(None, max_length=11)
    detected_address: str | None = Field(None, max_length=500)
    source_invoice_id: int | None = None
    confidence: float = Field(default=0, ge=0, le=100)


class PendingVendorPromote(BaseModel):
    master_id: str | None = Field(None, min_length=1, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=255)
    abn: str = ""
    default_ledger: str = ""
    status: str = "Active"


class PendingVendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    detected_name: str
    detected_abn: str | None
    detected_address: str | None
    source_invoice_id: int | None
    confidence: float
    status: str
    promoted_master_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class PendingCustomerCreate(BaseModel):
    detected_name: str = Field(..., min_length=1, max_length=255)
    detected_abn: str | None = Field(None, max_length=11)
    detected_address: str | None = Field(None, max_length=500)
    source_invoice_id: int | None = None
    confidence: float = Field(default=0, ge=0, le=100)


class PendingCustomerPromote(BaseModel):
    master_id: str | None = Field(None, min_length=1, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=255)
    abn: str = ""
    default_ledger: str = ""
    status: str = "Active"


class PendingCustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    detected_name: str
    detected_abn: str | None
    detected_address: str | None
    source_invoice_id: int | None
    confidence: float
    status: str
    promoted_master_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class MasterConfirmationSendResponse(BaseModel):
    sent: bool
    email: str | None = None
    error: str | None = None
    expires_at: datetime | None = None


class MasterConfirmationPreviewResponse(BaseModel):
    kind: str
    master_id: str
    party_name: str
    tenant_name: str
    expired: bool
    confirmed: bool
    fields: dict[str, object]


class MasterConfirmationSaveRequest(BaseModel):
    token: str
    fields: dict[str, object] = Field(default_factory=dict)


class MasterConfirmationSaveResponse(BaseModel):
    kind: str
    master_id: str
    party_name: str
    status: str
    confirmed_at: datetime
