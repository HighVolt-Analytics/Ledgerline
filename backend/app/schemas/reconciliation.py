from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    total_invoices: int
    total_ap_credits: Decimal
    total_debits: Decimal
    total_credits: Decimal
    is_balanced: bool
    halted: bool = False
    halt_reason: str | None = None
    run_at: datetime


class ReconPostingRow(BaseModel):
    account: str
    debit: Decimal
    credit: Decimal


class ReconInvoiceOverviewRow(BaseModel):
    id: str = Field(description="Document ref shown in the UI")
    invoice_id: int
    vendor: str
    total: Decimal
    postings: list[ReconPostingRow]


class ReconDayOverviewRow(BaseModel):
    date: date
    count: int
    sum_dr: Decimal
    sum_cr: Decimal
    delta: Decimal
    invoices: list[ReconInvoiceOverviewRow]


class ReconciliationOverview(BaseModel):
    sum_totals: Decimal
    sum_dr: Decimal
    sum_cr: Decimal
    delta_dr_cr: Decimal
    balanced: bool
    base_currency: str = "AUD"
    by_date: list[ReconDayOverviewRow]
