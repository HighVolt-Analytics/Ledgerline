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
    rc1_passed: bool | None = None
    rc2_passed: bool | None = None


class ReconciliationJournalLine(BaseModel):
    id: int
    invoice_id: int
    vendor: str | None = None
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    entry_type: str


class ReconciliationDayInvoice(BaseModel):
    id: int
    vendor: str | None = None
    invoice_no: str | None = None
    total: Decimal | None = None


class ReconciliationDayDetail(BaseModel):
    date: date
    invoices_total: Decimal
    total_debits: Decimal
    total_credits: Decimal
    delta_dr_cr: Decimal
    delta_vs_invoices: Decimal
    rc1_passed: bool
    rc2_passed: bool
    is_balanced: bool
    halt_reason: str | None = None
    journal_lines: list[ReconciliationJournalLine]
    invoices: list[ReconciliationDayInvoice]


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
    base_currency: str = ""
    by_date: list[ReconDayOverviewRow]
