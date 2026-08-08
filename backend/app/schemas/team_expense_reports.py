"""Team expense report row schemas for the Reports page."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class EmployeeAdvanceSettlementRow(BaseModel):
    employee_id: str
    name: str
    role: str = ""
    email: str = ""
    whatsapp_number: str = ""
    whatsapp_number_2: str = ""
    viber_number: str | None = None
    date_of_joining: str = ""
    department: str = ""
    location: str = ""
    division: str = ""
    supervisor_1: str = ""
    supervisor_2: str = ""
    bank_name: str = ""
    bank_account_name: str = ""
    bank_account_number: str = ""
    bank_bsb: str = ""
    bank_swift: str = ""
    bank_iban: str = ""
    advance_parent_ledger: str = ""
    advance_sub_ledger: str = ""
    status: str = ""
    claim_count: int = 0
    last_claim: str = ""
    claim_ytd_spent: float = Field(
        0,
        description="YTD claim spend counter (expense claims only; not advance requisitions).",
    )
    advance_ledger_balance: Decimal = Decimal("0")
    advance_taken: Decimal = Field(
        Decimal("0"),
        description="Lifetime of Staff Advance debits (advance requisitions paid out).",
    )
    advance_used: Decimal = Field(
        Decimal("0"),
        description="Lifetime of Staff Advance credits (claims that netted the advance).",
    )
    pending_against_advance: Decimal = Field(
        Decimal("0"),
        description="Open expense claims that reserve Staff Advance float until posted.",
    )
    available_advance: Decimal = Decimal("0")


class EmployeeBudgetUtilizationRow(BaseModel):
    employee_id: str
    name: str
    role: str = ""
    email: str = ""
    whatsapp_number: str = ""
    whatsapp_number_2: str = ""
    viber_number: str | None = None
    date_of_joining: str = ""
    department: str = ""
    location: str = ""
    division: str = ""
    supervisor_1: str = ""
    supervisor_2: str = ""
    bank_name: str = ""
    bank_account_name: str = ""
    bank_account_number: str = ""
    bank_bsb: str = ""
    bank_swift: str = ""
    bank_iban: str = ""
    status: str = ""
    budget_monthly: float = 0
    budget_quarterly: float = 0
    budget_annual: float = 0
    category_caps: str = Field(
        "",
        description="Readable category caps as 'ledger:cap; ...'.",
    )
    mtd_spent: float = 0
    qtd_spent: float = 0
    ytd_spent: float = 0
    claim_count: int = 0
    last_claim: str = ""
    monthly_remaining: float | None = None
    quarterly_remaining: float | None = None
    annual_remaining: float | None = None
    monthly_utilization_pct: float | None = None
    quarterly_utilization_pct: float | None = None
    annual_utilization_pct: float | None = None
    # Cash view: outstanding advance float still holds company cash even though it
    # is not P&L spend. cash_committed = period claim spend + advance_float.
    advance_float: float = Field(
        0,
        description="Outstanding Staff Advance ledger balance (asset / cash float).",
    )
    monthly_cash_committed: float = 0
    quarterly_cash_committed: float = 0
    annual_cash_committed: float = 0
    monthly_cash_remaining: float | None = None
    quarterly_cash_remaining: float | None = None
    annual_cash_remaining: float | None = None
    monthly_cash_utilization_pct: float | None = None
    quarterly_cash_utilization_pct: float | None = None
    annual_cash_utilization_pct: float | None = None


class EmployeeExpenseSummaryRow(BaseModel):
    employee_id: str = ""
    employee_name: str = ""
    role: str = ""
    employee_email: str = ""
    mobile: str = ""
    department: str = ""
    division: str = ""
    location: str = ""
    document_no: str = ""
    invoice_date: date | None = None
    team_expense_kind: str = ""
    document_type_code: str = ""
    line_description: str = ""
    line_qty: Decimal | None = None
    line_amount: Decimal | None = None
    ledger_code: str = ""
    main_gl: str = Field("", description="Parent expense GL for the posted account.")
    sub_ledger: str = Field("", description="Expense Sub-GL when posted to a child / line sub-ledger.")
    status: str = ""
    evaluation_status: str = ""
    invoice_id: int
    currency: str = ""


class EmployeeMasterReportRow(BaseModel):
    """Static employee master (Excel columns A-V)."""

    employee_id: str
    name: str
    role: str = ""
    email: str = ""
    whatsapp_number: str = ""
    whatsapp_number_2: str = ""
    viber_number: str | None = None
    date_of_joining: str = ""
    department: str = ""
    location: str = ""
    division: str = ""
    supervisor_1: str = ""
    supervisor_2: str = ""
    bank_name: str = ""
    bank_account_name: str = ""
    bank_account_number: str = ""
    bank_bsb: str = ""
    bank_swift: str = ""
    bank_iban: str = ""
    advance_parent_ledger: str = ""
    advance_sub_ledger: str = ""
    status: str = ""


class EmployeeSpendDetailRow(BaseModel):
    """One row per employee x expense Sub-GL (master A-V + spend columns)."""

    employee_id: str
    name: str
    role: str = ""
    email: str = ""
    whatsapp_number: str = ""
    whatsapp_number_2: str = ""
    viber_number: str | None = None
    date_of_joining: str = ""
    department: str = ""
    location: str = ""
    division: str = ""
    supervisor_1: str = ""
    supervisor_2: str = ""
    bank_name: str = ""
    bank_account_name: str = ""
    bank_account_number: str = ""
    bank_bsb: str = ""
    bank_swift: str = ""
    bank_iban: str = ""
    advance_parent_ledger: str = ""
    advance_sub_ledger: str = ""
    status: str = ""
    main_gl: str = Field("", description="Parent expense GL for the claim wallet.")
    sub_ledger: str = Field("", description="Expense Sub-GL / claim account posted.")
    sub_gl_budget: float = Field(
        0,
        description="Current-period Sub-GL budget (annual preferred, else quarterly/monthly).",
    )
    employee_spend_ytd: float = Field(
        0,
        description="YTD processed expense-claim totals posted to this Sub-GL.",
    )
    pct_of_sub_gl_used: float | None = Field(
        None,
        description="Employee Spend YTD / Sub-GL Budget * 100.",
    )
    claim_count: int = Field(0, description="YTD processed claims on this Sub-GL.")
    advance_pending: Decimal = Field(
        Decimal("0"),
        description="Open expense claims reserving Staff Advance float (employee-level).",
    )
    cash_reimbursed_ytd: float = Field(
        0,
        description="YTD settlement credits on claims for this Sub-GL (cash paid to employee).",
    )
    last_claim_date: str = ""
    # Employee spending-limit envelope (same math as budget-utilization; repeats per Sub-GL row).
    budget_monthly: float = 0
    budget_quarterly: float = 0
    budget_annual: float = 0
    mtd_spent: float = Field(
        0, description="Employee-level MTD claim spend (all Sub-GLs; advances excluded)."
    )
    qtd_spent: float = Field(
        0, description="Employee-level QTD claim spend (all Sub-GLs; advances excluded)."
    )
    ytd_spent_total: float = Field(
        0, description="Employee-level YTD claim spend (all Sub-GLs; advances excluded)."
    )
    monthly_remaining: float | None = None
    quarterly_remaining: float | None = None
    annual_remaining: float | None = None
    monthly_utilization_pct: float | None = None
    quarterly_utilization_pct: float | None = None
    annual_utilization_pct: float | None = None


class EmployeeAdvanceDetailRow(BaseModel):
    """One row per advance take or claim netting movement (employee float ledger)."""

    employee_id: str
    name: str
    role: str = ""
    email: str = ""
    whatsapp_number: str = ""
    whatsapp_number_2: str = ""
    viber_number: str | None = None
    date_of_joining: str = ""
    department: str = ""
    location: str = ""
    division: str = ""
    supervisor_1: str = ""
    supervisor_2: str = ""
    bank_name: str = ""
    bank_account_name: str = ""
    bank_account_number: str = ""
    bank_bsb: str = ""
    bank_swift: str = ""
    bank_iban: str = ""
    advance_parent_ledger: str = ""
    advance_sub_ledger: str = ""
    status: str = Field("", description="Employee master status (Active/Inactive).")
    movement_type: str = Field(
        "",
        description="Advance = Took; Claim = Used (Staff Advance credit).",
    )
    document_no: str = ""
    document_date: date | None = None
    took: Decimal = Field(
        Decimal("0"),
        description="This row's advance payout (Staff Advance debit).",
    )
    used: Decimal = Field(
        Decimal("0"),
        description="This row's advance cleared by claim (Staff Advance credit).",
    )
    outstanding_after: Decimal = Field(
        Decimal("0"),
        description="Running Staff Advance float after this movement.",
    )
    pending_claims: Decimal = Field(
        Decimal("0"),
        description="Open claims reserving float (current employee snapshot).",
    )
    available: Decimal = Field(
        Decimal("0"),
        description="Current Available = Outstanding - Pending Claims (employee snapshot).",
    )
    cash_reimbursed: Decimal = Field(
        Decimal("0"),
        description="Settlement credit on this claim (0 on advance rows).",
    )
    document_status: str = ""
    approved_by: str = ""
    approved_on: str = ""
    invoice_id: int = 0
