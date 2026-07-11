"""Billing and credits schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import UserResponse


class PlanInfo(BaseModel):
    plan: str
    region: str
    currency_code: str
    monthly_credits: int
    max_users: int
    social_integration: bool
    email_integration: bool
    studio_monthly_price: float
    credits_per_page: int
    topup_factor: float


class CreditLedgerEntryResponse(BaseModel):
    id: int
    event_type: str
    description: str
    pages: int | None = None
    credits_per_page: int | None = None
    credits_delta: int
    balance_after: int
    plan_at_event: str | None = None
    amount_paid: float | None = None
    currency_code: str | None = None
    azure_cost_usd: float | None = None
    azure_cost_breakdown: dict[str, Any] | None = None
    filename: str | None = None
    invoice_id: int | None = None
    stripe_hosted_invoice_url: str | None = None
    stripe_receipt_url: str | None = None
    created_at: datetime | None = None


class BillingStateResponse(BaseModel):
    balance: int
    plan: str
    credits_per_page: int
    credits_consumed: int = 0
    plan_info: PlanInfo
    billing_anchor_date: str | None = None
    fy_days_remaining: int | None = None
    can_upgrade_studio: bool = True
    can_top_up: bool = True
    is_enterprise: bool = False
    platform_billing_enabled: bool = False
    subscription_status: str | None = None


class BillingUsageHistoryResponse(BaseModel):
    items: list[CreditLedgerEntryResponse]
    total: int
    page: int
    pages: int


class BillingTopUpRequest(BaseModel):
    amount: Decimal = Field(gt=0, description="Amount in tenant regional currency")


class BillingUpgradeRequest(BaseModel):
    plan: str = Field(default="studio", pattern=r"^(studio)$")


class BillingPlanCatalogItem(BaseModel):
    plan_code: str
    region: str
    currency_code: str
    monthly_credits: int
    max_users: int
    social_integration: bool
    email_integration: bool
    monthly_price: float
    credits_per_page: int = 5


class BillingPlansResponse(BaseModel):
    country: str
    region: str
    currency_code: str
    plans: list[BillingPlanCatalogItem]
    platform_billing_enabled: bool = False


class BillingSignupCheckoutRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    organisation_name: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=2, max_length=2)
    plan_code: str = Field(pattern=r"^(free|studio)$")
    industry: str | None = Field(default=None, max_length=64)
    full_name: str | None = Field(default=None, max_length=255)
    signup_token: str | None = Field(default=None, max_length=128)
    signup_source: str = Field(default="public", pattern=r"^(public|invite)$")


class BillingTopUpCheckoutRequest(BaseModel):
    amount: Decimal = Field(gt=0, description="Amount in tenant regional currency")


class CheckoutSessionResponse(BaseModel):
    checkout_url: str | None = None
    session_id: str | None = None
    status: str
    pending_signup_id: str | None = None
    tenant_id: str | None = None
    completed_without_checkout: bool = False
    access_token: str | None = None
    refresh_token: str | None = None
    user: UserResponse | None = None


class CheckoutStatusResponse(BaseModel):
    session_id: str
    status: str | None = None
    payment_status: str | None = None
    mode: str | None = None
    event_type: str | None = None
    tenant_id: str | None = None
    email: str | None = None
    fulfilled: bool = False


class PlatformCreditSettingsResponse(BaseModel):
    credits_per_page: int
    universal_credits_per_page: bool
    topup_factor_in: float
    topup_factor_sg: float
    topup_factor_au: float


class PlatformCreditSettingsUpdate(BaseModel):
    credits_per_page: int | None = Field(default=None, ge=1)
    universal_credits_per_page: bool | None = None
    topup_factor_in: float | None = Field(default=None, gt=0)
    topup_factor_sg: float | None = Field(default=None, gt=0)
    topup_factor_au: float | None = Field(default=None, gt=0)


class PlatformTenantBillingUpdate(BaseModel):
    plan: str | None = Field(default=None, pattern=r"^(free|studio|enterprise)$")
    enterprise_monthly_credits: int | None = Field(default=None, ge=0)
    credits_per_page_override: int | None = Field(default=None, ge=1)
    grant_credits: int | None = None
