"""Budget, concentration & risk dashboard payload."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class BudgetDepartmentRow(BaseModel):
    name: str
    budget: Decimal = Decimal("0")
    actual: Decimal = Decimal("0")
    committed: Decimal = Decimal("0")
    owner: str = ""


class BudgetEncumbranceSummary(BaseModel):
    budget: Decimal = Decimal("0")
    actual: Decimal = Decimal("0")
    committed: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    utilisation_pct: Decimal | None = None


class VendorConcentrationRow(BaseModel):
    name: str
    spend: Decimal = Decimal("0")
    invoice_count: int = 0
    cycle_days: Decimal | None = None
    po_backed_pct: Decimal | None = None
    risk_level: str = "Low"
    bank_change_flag: bool = False


class VendorConcentrationSummary(BaseModel):
    top10_concentration_pct: Decimal | None = None
    non_po_spend_pct: Decimal | None = None
    contracted_in_top10: int = 0
    high_risk_count: int = 0


class BudgetConcentrationRiskMeta(BaseModel):
    currency: str
    period_label: str
    as_of: str
    period_start: str
    period_end: str
    budget_group_label: str = "department / GL"
    environment_label: str | None = None
    coverage_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BudgetConcentrationRiskDashboard(BaseModel):
    meta: BudgetConcentrationRiskMeta
    departments: list[BudgetDepartmentRow]
    budget_summary: BudgetEncumbranceSummary
    vendors: list[VendorConcentrationRow]
    vendor_summary: VendorConcentrationSummary
