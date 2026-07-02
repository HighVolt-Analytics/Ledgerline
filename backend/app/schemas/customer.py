"""Customer registry and master schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.rule_book_config import BillingAddress


class CustomerCreate(BaseModel):
    customer_slug: str = Field(..., min_length=1, max_length=100)
    customer_name: str = Field(..., min_length=1, max_length=255)
    sender_pattern: str = Field(..., min_length=1, max_length=255)
    abn: str | None = Field(None, min_length=11, max_length=11)
    approved: bool = False


class CustomerUpdate(BaseModel):
    customer_name: str | None = Field(None, min_length=1, max_length=255)
    sender_pattern: str | None = Field(None, min_length=1, max_length=255)
    abn: str | None = Field(None, min_length=11, max_length=11)
    approved: bool | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_slug: str
    customer_name: str
    sender_pattern: str
    abn: str | None
    approved: bool
    created_at: datetime


class CustomerMaster(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    abn: str = ""
    billing_address: BillingAddress = Field(default_factory=BillingAddress)
    default_ledger: str = ""
    default_sub_ledger: str = ""
    payment_terms: str = ""
    status: str = ""
    registered_on: str = ""
    total_revenue_ytd: float = Field(default=0, ge=0)
    invoice_count: int = Field(default=0, ge=0)
    match_confidence: float = Field(default=0, ge=0, le=100)


class CustomerMasterCreate(BaseModel):
    master_id: str | None = Field(None, min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    abn: str = ""
    billing_address: BillingAddress = Field(default_factory=BillingAddress)
    default_ledger: str = ""
    default_sub_ledger: str = ""
    payment_terms: str = ""
    status: str = "Pending registration"
    registered_on: str = ""
    total_revenue_ytd: float = Field(default=0, ge=0)
    invoice_count: int = Field(default=0, ge=0)
    match_confidence: float = Field(default=0, ge=0, le=100)


class CustomerMasterUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    aliases: list[str] | None = None
    abn: str | None = None
    billing_address: BillingAddress | None = None
    default_ledger: str | None = None
    default_sub_ledger: str | None = None
    payment_terms: str | None = None
    status: str | None = None
    registered_on: str | None = None
    total_revenue_ytd: float | None = Field(None, ge=0)
    invoice_count: int | None = Field(None, ge=0)
    match_confidence: float | None = Field(None, ge=0, le=100)


class CustomerMasterResponse(CustomerMaster):
    """Public customer master shape (id = master_id)."""

    db_id: int
