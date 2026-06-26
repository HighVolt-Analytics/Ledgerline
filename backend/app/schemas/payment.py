"""Payment workflow schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PaymentResponse(BaseModel):
    id: int
    invoice_id: int
    vendor: str | None = None
    amount: float
    currency: str = "AUD"
    status: str
    tab: str
    due_date: date | None = None
    scheduled_date: date | None = None
    paid_date: datetime | None = None
    invoice_approved_by: int | None = None
    approvers: list[dict[str, Any]] = Field(default_factory=list)
    payment_intent: str | None = None
    failure_reason: str | None = None


class PaymentStatusUpdate(BaseModel):
    status: str
    scheduled_date: date | None = None
    payment_intent: str | None = None
    failure_reason: str | None = None


class WalletTransactionResponse(BaseModel):
    id: str
    label: str
    delta: float


class WalletSummaryResponse(BaseModel):
    balance: float
    available: float
    last_top_up: str
    transactions: list[WalletTransactionResponse] = Field(default_factory=list)


class StripeAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: uuid.UUID
    stripe_account_id: str
    account_type: str | None = None
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    onboarding_status: str | None = None
    created_at: datetime
    updated_at: datetime


class StripeConnectResponse(BaseModel):
    account: StripeAccountResponse
    onboarding_url: str | None = None


class StripeOnboardingLinkResponse(BaseModel):
    url: str


class StripeOAuthUrlResponse(BaseModel):
    url: str


class StripeDisconnectResponse(BaseModel):
    disconnected: bool


class StripeReadinessResponse(BaseModel):
    connected: bool
    account_id: str | None = None
    onboarding_status: str | None = None
    charges_enabled: bool
    payouts_enabled: bool
    ready_for_charges: bool
    ready_for_payouts: bool
    blocking_reason: str | None = None
    recommended_action: str | None = None


class StripeBalanceAmountResponse(BaseModel):
    amount: float | None = None
    currency: str | None = None


class StripeBalanceResponse(BaseModel):
    available: list[StripeBalanceAmountResponse] = Field(default_factory=list)
    pending: list[StripeBalanceAmountResponse] = Field(default_factory=list)
    livemode: bool
    snapshot_id: int


class StripeTransactionResponse(BaseModel):
    id: int
    stripe_transaction_id: str
    type: str | None = None
    amount: float | None = None
    currency: str | None = None
    status: str | None = None
    description: str | None = None
    available_on: str | None = None


class PaymentAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: int
    stripe_payment_intent_id: str | None = None
    stripe_transfer_id: str | None = None
    stripe_payout_id: str | None = None
    amount: float | None = None
    currency: str | None = None
    status: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    created_at: datetime
    updated_at: datetime
