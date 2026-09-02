"""CFO alerts & threshold breaches dashboard payload."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class CfoAlertRow(BaseModel):
    severity: str  # high | med | low
    title: str
    detail: str
    meta: str = ""
    module: str = ""
    source: str = ""


class CfoAlertsSummary(BaseModel):
    active_count: int = 0
    high_count: int = 0
    med_count: int = 0
    low_count: int = 0


class CfoAlertsMeta(BaseModel):
    currency: str
    period_label: str
    as_of: str
    period_start: str
    period_end: str
    environment_label: str | None = None
    coverage_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CfoAlertsDashboard(BaseModel):
    meta: CfoAlertsMeta
    summary: CfoAlertsSummary
    alerts: list[CfoAlertRow]
