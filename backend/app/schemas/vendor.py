"""Vendor registry schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PayoutMethodType = Literal[
    "manual_bank",
    "stripe_connected_account",
    "external_bank_phase2",
    "stripe_global_payouts",
    "stripe_treasury",
    "external_ap_provider",
]
PayoutMethodStatus = Literal[
    "not_configured",
    "pending",
    "verified",
    "failed",
    "disabled",
]
PayoutProvider = Literal[
    "manual_bank",
    "stripe_global_payouts",
    "stripe_treasury",
    "external_ap_provider",
]
RecipientStatus = Literal[
    "not_configured",
    "pending",
    "verified",
    "failed",
    "disabled",
]


class VendorCreate(BaseModel):
    vendor_slug: str = Field(..., min_length=1, max_length=100)
    vendor_name: str = Field(..., min_length=1, max_length=255)
    sender_pattern: str = Field(..., min_length=1, max_length=255)
    abn: str | None = Field(None, min_length=11, max_length=11)
    approved: bool = False


class VendorUpdate(BaseModel):
    vendor_name: str | None = Field(None, min_length=1, max_length=255)
    sender_pattern: str | None = Field(None, min_length=1, max_length=255)
    abn: str | None = Field(None, min_length=11, max_length=11)
    approved: bool | None = None


class VendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vendor_slug: str
    vendor_name: str
    sender_pattern: str
    abn: str | None
    approved: bool
    created_at: datetime


class VendorPayoutMethodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vendor_id: int
    method_type: str
    display_label: str | None = None
    stripe_account_id: str | None = None
    last4: str | None = None
    currency: str = "AUD"
    status: str
    is_default: bool
    provider: str | None = None
    provider_recipient_id: str | None = None
    recipient_status: str | None = None
    recipient_country: str | None = None
    recipient_currency: str | None = None
    created_at: datetime
    updated_at: datetime


class VendorPayoutMethodCreate(BaseModel):
    method_type: PayoutMethodType
    display_label: str | None = Field(None, max_length=255)
    stripe_account_id: str | None = Field(None, max_length=255)
    last4: str | None = Field(None, max_length=4)
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    status: PayoutMethodStatus = "pending"
    is_default: bool = True


class VendorPayoutMethodUpdate(BaseModel):
    method_type: PayoutMethodType | None = None
    display_label: str | None = Field(None, max_length=255)
    stripe_account_id: str | None = Field(None, max_length=255)
    last4: str | None = Field(None, max_length=4)
    currency: str | None = Field(None, min_length=3, max_length=3)
    status: PayoutMethodStatus | None = None
    is_default: bool | None = None
