from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.journal import JournalEntryResponse
from app.schemas.line_item import LineItemResponse

PipelineStageState = Literal["done", "pending", "fail", "skipped"]


class InvoiceStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    VALIDATING = "validating"
    MAPPING = "mapping"
    JOURNALING = "journaling"
    RECONCILING = "reconciling"
    PROCESSED = "processed"
    EXCEPTION = "exception"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    REJECTED = "rejected"


class EvaluationStatus(str, Enum):
    AUTO_CODED = "auto_coded"
    NEEDS_REVIEW = "needs_review"
    PENDING_VENDOR = "pending_vendor"
    UNMATCHED_EXPENSE_VENDOR = "unmatched_expense_vendor"
    AWAITING_PO = "awaiting_po"


class ValidationResultItem(BaseModel):
    rule: str
    passed: bool
    message: str
    skipped: bool = False


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_ref: str | None = None
    vendor: str | None
    abn: str | None
    invoice_no: str | None
    po_reference: str | None = None
    cost_centre: str | None = None
    invoice_date: date | None
    due_date: date | None
    currency: str
    subtotal: Decimal | None
    gst: Decimal | None
    total: Decimal | None
    status: InvoiceStatus
    file_hash: str | None
    raw_file_path: str | None
    email_sender: str | None = None
    capture_source: str | None = None
    connected_mailbox_id: int | None = None
    storage_vendor_slug: str | None = None
    account_code: str | None = None
    account_name: str | None = None
    route_target: str | None = None
    matched_rule_ids: list[str] | None = None
    vendor_confidence: float | None = None
    evaluation_status: EvaluationStatus | None = None
    purchase_document_type: str | None = None
    document_type_code: str | None = None
    document_type_confidence: float | None = None
    document_type_extraction_fields: list[str] | None = None
    bank_bsb: str | None = None
    bank_account: str | None = None
    email_attachment_name: str | None = None
    billing_address: str | None = None
    email_subject: str | None = None
    document_text: str | None = None
    validation_results: list[ValidationResultItem] | None = None
    extraction_field_confidence: dict[str, float] | None = None
    created_at: datetime
    has_stored_file: bool = False
    published_to_ledger: bool = False
    current_stage: str = "Received"
    current_stage_state: PipelineStageState = "pending"


class InvoiceWithDetails(InvoiceResponse):
    line_items: list[LineItemResponse] = Field(default_factory=list)
    journal_entries: list[JournalEntryResponse] = Field(default_factory=list)


class LineItemUpdateRequest(BaseModel):
    id: int | None = None
    description: str | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    tax_amount: Decimal | None = None


class InvoiceUpdateRequest(BaseModel):
    vendor: str | None = None
    abn: str | None = None
    invoice_no: str | None = None
    po_reference: str | None = None
    cost_centre: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    gst: Decimal | None = None
    total: Decimal | None = None
    account_code: str | None = None
    account_name: str | None = None
    line_items: list[LineItemUpdateRequest] | None = None


class ProcessInvoicesBatchRequest(BaseModel):
    invoice_ids: list[int] = Field(min_length=1, max_length=50)
