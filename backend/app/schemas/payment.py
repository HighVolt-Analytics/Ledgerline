"""Payment workflow schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


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
