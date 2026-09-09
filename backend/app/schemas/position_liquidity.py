"""Position & Liquidity dashboard KPI payload."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class PositionLiquidityMeta(BaseModel):
    currency: str = Field(description="Consolidated reporting currency (tenant base)")
    period_label: str = Field(description="Human-readable period, e.g. FY26 YTD to 31 Aug 2026")
    as_of: str = Field(description="Balance as-of date (ISO)")
    period_start: str = Field(description="Activity window start (ISO)")
    period_end: str = Field(description="Activity window end (ISO)")
    environment_label: str | None = Field(
        default=None,
        description="Tenant or environment tag shown in the dashboard header",
    )
    coverage_gaps: list[str] = Field(
        default_factory=list,
        description="Known control gaps excluded from headline KPIs (explicit scope boundaries)",
    )
    notes: list[str] = Field(default_factory=list)


class CurrencyAmount(BaseModel):
    """Native-currency total — no FX conversion into tenant base."""

    currency: str
    amount: Decimal = Decimal("0")


class PositionLiquidityKpis(BaseModel):
    # TODO(confirm-schema): Invoice Register unpaid + AP route — per-currency, no FX
    ap_outstanding_by_currency: list[CurrencyAmount] = Field(default_factory=list)
    approved_not_paid_by_currency: list[CurrencyAmount] = Field(default_factory=list)
    due_next_7_days_by_currency: list[CurrencyAmount] = Field(default_factory=list)
    overdue: Decimal = Decimal("0")
    overdue_1_30: Decimal = Decimal("0")
    overdue_31_60: Decimal = Decimal("0")
    overdue_61_90: Decimal = Decimal("0")
    overdue_90_plus: Decimal = Decimal("0")
    dpo_days: Decimal | None = None
    dpo_prior_year_days: Decimal | None = None
    on_time_payment_rate_pct: Decimal | None = None
    discount_capture_rate_pct: Decimal | None = None
    budget_utilisation_pct: Decimal | None = None
    advances_outstanding: Decimal = Decimal("0")
    open_exceptions_count: int = 0
    claims_pending_count: int = 0
    documents_to_review_count: int = 0
    payments_queue_count: int = 0
    vendor_top10_concentration_pct: Decimal | None = None
    vendor_non_po_spend_pct: Decimal | None = None


class PositionLiquidityDashboard(BaseModel):
    meta: PositionLiquidityMeta
    kpis: PositionLiquidityKpis
