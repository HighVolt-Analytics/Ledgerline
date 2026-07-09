"""Spend analytics schemas for the Reports page."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ReportDocumentRow(BaseModel):
    id: int
    document_ref: str
    vendor: str
    account: str
    invoice_date: date | None = None
    period_key: str = Field(description="YYYY-MM derived from invoice date")
    subtotal: Decimal
    gst: Decimal
    total: Decimal
    currency: str


class GlAccountSpendRow(BaseModel):
    account: str
    amount: Decimal
    count: int


class VendorSpendRow(BaseModel):
    vendor: str
    amount: Decimal
    count: int


class ReportsKpiTrends(BaseModel):
    net_spend_delta_pct: float | None = None
    tax_delta_pct: float | None = None
    gross_spend_delta_pct: float | None = None
    documents_delta: int | None = None


class ReportsAnalytics(BaseModel):
    base_currency: str = ""
    tax_label: str = "Tax"
    period_key: str
    period_label: str
    net_spend: Decimal
    tax_total: Decimal
    gross_spend: Decimal
    document_count: int
    by_gl_account: list[GlAccountSpendRow]
    top_vendors: list[VendorSpendRow]
    kpi_trends: ReportsKpiTrends
    period_has_data: bool
