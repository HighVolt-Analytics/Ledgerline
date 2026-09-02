"""Process efficiency trends dashboard payload — rolling monthly DPO + STP."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class ProcessEfficiencyTrendPoint(BaseModel):
    label: str
    period_start: str
    period_end: str
    dpo_days: Decimal | None = None
    stp_pct: Decimal | None = None


class ProcessEfficiencyTrendsSummary(BaseModel):
    stp_target_pct: Decimal = Decimal("85")
    latest_dpo_days: Decimal | None = None
    latest_stp_pct: Decimal | None = None
    months_with_dpo: int = 0
    months_with_stp: int = 0


class ProcessEfficiencyTrendsMeta(BaseModel):
    currency: str
    period_label: str
    as_of: str
    window_start: str
    window_end: str
    environment_label: str | None = None
    coverage_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProcessEfficiencyTrendsDashboard(BaseModel):
    meta: ProcessEfficiencyTrendsMeta
    points: list[ProcessEfficiencyTrendPoint]
    summary: ProcessEfficiencyTrendsSummary
