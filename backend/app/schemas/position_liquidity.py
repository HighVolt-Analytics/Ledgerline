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


class PositionLiquidityKpis(BaseModel):
    ap_outstanding: Decimal = Decimal("0")
    approved_not_paid: Decimal = Decimal("0")
    due_next_7_days: Decimal = Decimal("0")
    due_next_14_days: Decimal = Decimal("0")
    due_next_30_days: Decimal = Decimal("0")
    overdue: Decimal = Decimal("0")
    overdue_pct: Decimal | None = None
    overdue_threshold_pct: Decimal = Field(
        default=Decimal("10"),
        description="Covenant/policy threshold for overdue % of AP (hardcoded default)",
    )
    dpo_days: Decimal | None = None
    dpo_prior_year_days: Decimal | None = None
    on_time_payment_rate_pct: Decimal | None = None
    discount_capture_rate_pct: Decimal | None = None
    budget_utilisation_pct: Decimal | None = None
    budget_actual: Decimal = Decimal("0")
    budget_allocated: Decimal = Decimal("0")
    budget_committed: Decimal = Decimal("0")
    advances_outstanding: Decimal = Decimal("0")
    advances_overdue: Decimal = Decimal("0")
    advances_overdue_employees: int = 0
    open_exceptions_count: int = 0
    open_exceptions_at_risk: Decimal = Decimal("0")
    claims_pending_count: int = 0
    claims_pending_value: Decimal = Decimal("0")
    documents_to_review_count: int = 0
    documents_to_review_value: Decimal = Decimal("0")
    documents_processing_count: int = 0
    documents_processing_value: Decimal = Decimal("0")
    payments_queue_count: int = 0
    payments_queue_value: Decimal = Decimal("0")
    vendor_top10_concentration_pct: Decimal | None = None
    vendor_non_po_spend_pct: Decimal | None = None


class PositionLiquidityDashboard(BaseModel):
    meta: PositionLiquidityMeta
    kpis: PositionLiquidityKpis
