from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.invoice import InvoiceStatus


class NavBadges(BaseModel):
    """Lightweight sidebar counters (avoids full stats query on every layout mount)."""

    inbox_count: int
    pending_approval: int
    pending_classification: int = 0
    team_expenses_count: int = 0
    business_expenses_count: int = 0
    sales_count: int = 0
    payments_queue_count: int = 0
    collections_queue_count: int = 0
    integrations_connected: int


class DashboardStats(BaseModel):
    total_invoices: int
    invoices_this_month: int
    processed: int
    exceptions: int
    pending: int
    inbox_count: int
    duplicates_skipped: int
    rejected: int = 0
    pending_approval: int
    base_currency: str = Field(
        default="AUD",
        description="Reporting currency for converted totals",
    )
    total_value: Decimal = Field(
        default=Decimal("0"),
        description="Period total converted to base_currency",
    )
    value_by_currency: dict[str, Decimal] = Field(
        default_factory=dict,
        description="Raw period totals grouped by invoice currency",
    )
    total_value_aud: Decimal = Field(
        default=Decimal("0"),
        description="Alias of total_value when base_currency is AUD",
    )
    synced_percent: int = 0
    avg_processing_seconds: float | None = None
    last_reconciliation_balanced: bool | None = None
    reconciliation_delta_dr_cr: Decimal | None = None
    integrations_connected: int = 0
    distinct_vendors: int = 0
    docs_via_email: int = 0
    docs_via_upload: int = 0
    mailboxes_mapped: int = 0
    active_users: int = 0


class ActivityItem(BaseModel):
    id: int
    invoice_id: int | None
    document_ref: str | None = None
    event: str
    detail: dict[str, object] | None
    created_at: datetime
    vendor: str | None = None
    status: InvoiceStatus | None = None
    summary: str | None = None


class TopVendorRow(BaseModel):
    vendor: str
    amount: Decimal
    invoice_count: int
    counterparty_label: str = "Counterparty"


class CashForecastBucket(BaseModel):
    label: str
    amount: Decimal


class MailboxBreakdownRow(BaseModel):
    mailbox_id: int
    email: str
    display_name: str | None
    is_active: bool
    last_poll_at: datetime | None
    document_count: int


class AnomalyRow(BaseModel):
    tag: str
    description: str
    invoice_id: int | None = None
    document_ref: str | None = None


class KpiTrend(BaseModel):
    direction: Literal["up", "down", "flat"]
    text: str
    favorable: bool | None = None


class KpiSparklines(BaseModel):
    """Daily series for the last 7 days in period (oldest first)."""

    invoice_volume: list[int] = Field(default_factory=list)
    docs_via_email: list[int] = Field(default_factory=list)
    docs_via_upload: list[int] = Field(default_factory=list)
    total_value: list[int] = Field(
        default_factory=list,
        description="Daily converted totals in base currency (whole units)",
    )
    distinct_vendors: list[int] = Field(default_factory=list)
    mailboxes_active: list[int] = Field(
        default_factory=list,
        description="Distinct mailboxes that received docs each day",
    )
    active_users: list[int] = Field(default_factory=list)
    avg_processing_seconds: list[int] = Field(
        default_factory=list,
        description="Mean processing seconds for invoices completed each day",
    )
    reconciliation_delta: list[int] = Field(
        default_factory=list,
        description="Daily |debits - credits| in cents for org journals",
    )


class DashboardOverview(BaseModel):
    period: str = Field(description="Selected month as YYYY-MM")
    period_has_data: bool = Field(
        description="True when at least one invoice was received in the selected period"
    )
    cash_forecast_scope: str = Field(
        default="All open payables for your organisation"
    )
    stats: DashboardStats
    activity: list[ActivityItem]
    top_vendors: list[TopVendorRow]
    cash_forecast: list[CashForecastBucket]
    mailbox_breakdown: list[MailboxBreakdownRow]
    anomalies: list[AnomalyRow]
    kpi_trends: dict[str, KpiTrend]
    kpi_sparklines: KpiSparklines
    integrations_connected: int
    invoice_volume_sparkline: list[int] = Field(
        description="Alias of kpi_sparklines.invoice_volume for backward compatibility.",
    )
