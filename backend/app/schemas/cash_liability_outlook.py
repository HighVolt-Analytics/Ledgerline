"""Cash & liability outlook dashboard payload."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class CashOutlookWeek(BaseModel):
    week_start: str
    label: str
    confirmed_ap: Decimal = Decimal("0")
    probable_ap: Decimal = Decimal("0")
    recurring: Decimal = Decimal("0")
    reimbursements: Decimal = Decimal("0")
    advances: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total_outflow: Decimal = Decimal("0")
    available_balance: Decimal | None = None


class CashOutlookSummary(BaseModel):
    next_week_outflow: Decimal = Decimal("0")
    total_horizon_outflow: Decimal = Decimal("0")
    peak_week_outflow: Decimal = Decimal("0")
    peak_week_label: str = ""
    coverage_ratio: Decimal | None = None
    opening_cash_balance: Decimal | None = None


class ApAgeingBucket(BaseModel):
    bucket: str
    amount: Decimal = Decimal("0")


class CashLiabilityOutlookMeta(BaseModel):
    currency: str
    as_of: str
    period_label: str = ""
    period_start: str = ""
    period_end: str = ""
    horizon_weeks: int = 13
    environment_label: str | None = None
    coverage_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CashLiabilityOutlookDashboard(BaseModel):
    meta: CashLiabilityOutlookMeta
    weeks: list[CashOutlookWeek]
    summary: CashOutlookSummary
    ap_ageing: list[ApAgeingBucket]
    ap_ageing_total: Decimal = Decimal("0")
