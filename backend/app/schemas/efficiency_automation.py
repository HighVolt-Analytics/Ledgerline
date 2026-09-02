"""Efficiency & Automation Value dashboard KPI payload."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class EfficiencyAutomationMeta(BaseModel):
    currency: str = Field(description="Tenant books currency")
    period_label: str
    as_of: str
    period_start: str
    period_end: str
    month_start: str = Field(description="MTD window start (ISO)")
    environment_label: str | None = None
    coverage_gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EfficiencyAutomationKpis(BaseModel):
    touchless_processing_pct: Decimal | None = Field(
        default=None,
        description="Straight-through % from Process Efficiency (STP proxy)",
    )
    touchless_target_pct: Decimal = Field(
        default=Decimal("85"),
        description="Headline STP target (shared constant until configurable)",
    )
    first_pass_validation_pct: Decimal | None = Field(
        default=None,
        description="First-pass validation % — distinct from STP; same Process Efficiency slice",
    )
    straight_through_pct: Decimal | None = Field(
        default=None,
        description="Alias of touchless_processing_pct (STP); kept for card foot reconciliation",
    )
    cost_per_invoice: Decimal | None = None
    manual_cost_per_invoice_baseline: Decimal = Decimal("30.00")
    cost_improvement_pct: Decimal | None = None
    avg_processing_minutes: Decimal | None = None
    manual_processing_minutes_baseline: Decimal = Decimal("182")
    hours_saved_ytd: Decimal = Decimal("0")
    fte_equivalent: Decimal | None = None
    fte_hours_per_year: Decimal = Decimal("1830")
    documents_processed_ytd: int = 0
    documents_processed_mtd: int = 0
    documents_capture_email: int = 0
    documents_capture_upload: int = 0
    documents_capture_whatsapp: int = 0
    documents_capture_viber: int = 0
    vault_documents_total: int = 0
    duplicates_prevented_amount: Decimal = Decimal("0")
    duplicates_prevented_events: int = 0
    fraud_blocked_amount: Decimal = Decimal("0")
    fraud_blocked_events: int = 0
    discount_captured: Decimal | None = None
    discount_available: Decimal | None = None
    total_value_delivered: Decimal | None = None
    automation_savings_amount: Decimal = Decimal("0")
    sync_success_pct: Decimal | None = None
    sync_dead_letter_count: int = 0
    sync_providers_label: str = ""
    documents_past_retention: int = 0
    document_retention_days: int = 2555
    missing_supporting_docs: int = 0


class EfficiencyAutomationDashboard(BaseModel):
    meta: EfficiencyAutomationMeta
    kpis: EfficiencyAutomationKpis
