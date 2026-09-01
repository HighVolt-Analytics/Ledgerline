"""Payment workflow schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BankFileBatchExportRequest(BaseModel):
    """Select which Scheduled payments to bundle into one batch payment file
    (e.g. an AU ABA export). All must be Scheduled, not already exported, and
    in the currency the tenant's configured format expects.
    """

    payment_ids: list[int] = Field(min_length=1)


class PaymentExecutionInstructionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: int
    instruction_reference: str
    vendor_name: str | None = None
    vendor_payout_method_label: str | None = None
    amount: float
    currency: str = ""
    due_date: date | None = None
    execution_mode: str
    status: str
    created_by_name: str | None = None
    created_by_email: str | None = None
    created_at: datetime


class PaymentExecutionInstructionExportResponse(BaseModel):
    payment_id: int
    instruction_reference: str
    vendor_name: str | None = None
    vendor_payout_method_label: str | None = None
    amount: float
    currency: str = ""
    due_date: date | None = None
    execution_mode: str
    status: str
    created_by: str | None = None
    created_at: datetime
    export_format: str = "json"
    disclaimer: str


class PaymentMarkPaidManualRequest(BaseModel):
    reference: str = Field(min_length=1, max_length=255)
    paid_date: date
    proof_reference: str = Field(
        min_length=1,
        max_length=512,
        description="Proof of payment reference (file attachment integration planned)",
    )
    note: str | None = Field(default=None, max_length=2000)
    bank_payment_amount: float | None = Field(
        default=None,
        description="Amount actually paid in tenant base currency (from payment app).",
    )
    payment_fx_rate: float | None = Field(
        default=None,
        description="Payment-app FX rate (base = txn_amount * rate).",
    )


class PaymentResponse(BaseModel):
    id: int
    invoice_id: int
    vendor: str | None = None
    amount: float
    currency: str = ""
    status: str
    tab: str
    due_date: date | None = None
    scheduled_date: date | None = None
    paid_date: datetime | None = None
    invoice_approved_by: int | None = None
    approvers: list[dict[str, Any]] = Field(default_factory=list)
    payment_intent: str | None = None
    failure_reason: str | None = None
    vendor_payout_status: str | None = None
    vendor_payout_method_type: str | None = None
    execution_readiness_status: str | None = None
    execution_blocking_reason: str | None = None
    execution_instruction: PaymentExecutionInstructionResponse | None = None
    payment_fx_rate: float | None = None
    bank_payment_amount: float | None = None
    fx_variance: float | None = None


class PaymentWorkspaceKpis(BaseModel):
    open_count: int = 0
    overdue_count: int = 0
    due_soon_count: int = 0
    queue_count: int = 0
    awaiting_count: int = 0
    scheduled_count: int = 0
    paid_count: int = 0
    failed_count: int = 0
    outstanding_by_currency: dict[str, float] = Field(default_factory=dict)


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
    currency: str = ""
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
    model_config = ConfigDict(from_attributes=True)

    connected: bool
    account_id: str | None = None
    onboarding_status: str | None = None
    charges_enabled: bool
    payouts_enabled: bool
    ready_for_charges: bool
    ready_for_payouts: bool
    blocking_reason: str | None = None
    recommended_action: str | None = None


class StripeGlobalPayoutsReadinessResponse(BaseModel):
    enabled: bool
    access_status: str
    financial_account_configured: bool
    supported_countries: list[str] = Field(default_factory=list)
    supported_currencies: list[str] = Field(default_factory=list)
    max_amount_usd: float
    ready: bool
    blocking_reason: str | None = None
    recommended_action: str | None = None
    environment: str
    stripe_mode: str
    live_execution_enabled: bool


class StripeBalanceAmountResponse(BaseModel):
    amount: float | None = None
    currency: str | None = None


class StripeBalanceResponse(BaseModel):
    available: list[StripeBalanceAmountResponse] = Field(default_factory=list)
    pending: list[StripeBalanceAmountResponse] = Field(default_factory=list)
    livemode: bool
    snapshot_id: int


class StripeTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class PaymentExecutionReadinessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: int
    can_execute: bool
    execution_mode: str = "dry_run"
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tenant_stripe_ready: bool
    vendor_payout_ready: bool
    approval_ready: bool
    amount_ready: bool
    manual_execution_ready: bool = False
    role_ready: bool | None = None
    limit_ready: bool = True
    tenant_execution_enabled: bool = True
    recommended_action: str | None = None
    payments_execution_enabled: bool = False
    selected_payment_rail: str = "manual_instruction"
    stripe_global_payouts_ready: bool = False
    stripe_global_payouts_blocking_reason: str | None = None
    payment_rail_ready: bool = False
    payment_rail_recommended_action: str | None = None
    app_env: str = "preview"
    stripe_mode: str = "test"
    live_execution_enabled: bool = False
