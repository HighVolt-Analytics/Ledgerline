"""Styled Excel export for Team Expense reports (matches workbook_writer header style)."""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.team_expense_reports import (
    EmployeeAdvanceSettlementRow,
    EmployeeBudgetUtilizationRow,
    EmployeeExpenseSummaryRow,
)
from app.services.reports.team_expense_reports_service import (
    build_advance_settlement_rows,
    build_budget_utilization_rows,
    build_employee_expense_summary_rows,
)

HEADER_FILL = PatternFill("solid", fgColor="1F6E7A")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FILL = PatternFill("solid", fgColor="1F6E7A")
TITLE_FONT = Font(color="FFFFFF", bold=True, size=14)
SUBTITLE_FONT = Font(size=9, color="334455")
BODY_FONT = Font(size=10)
ZEBRA_FILL = PatternFill("solid", fgColor="F3F7F8")

SHEET_ADVANCE = "Employee Advance Settlement"
SHEET_BUDGET = "Employee Budget Utilization"
SHEET_SUMMARY = "Employee Expense Summary"

ADVANCE_HEADERS = [
    "Employee ID",
    "Employee Name",
    "Role",
    "Email",
    "Mobile",
    "Mobile (secondary)",
    "Viber",
    "Date of Joining",
    "Department",
    "Division",
    "Location",
    "Supervisor 1",
    "Supervisor 2",
    "Bank Name",
    "Bank Account Name",
    "Bank Account Number",
    "BSB",
    "SWIFT",
    "IBAN",
    "Advance Parent Ledger",
    "Advance Sub-Ledger",
    "Employee Status",
    "Claim Count",
    "Last Claim Date",
    "Claim YTD Spent",
    "Advance Ledger Balance",
    "Pending Against Advance",
    "Available Advance",
]

BUDGET_HEADERS = [
    "Employee ID",
    "Employee Name",
    "Role",
    "Email",
    "Mobile",
    "Mobile (secondary)",
    "Viber",
    "Date of Joining",
    "Department",
    "Division",
    "Location",
    "Supervisor 1",
    "Supervisor 2",
    "Bank Name",
    "Bank Account Name",
    "Bank Account Number",
    "BSB",
    "SWIFT",
    "IBAN",
    "Employee Status",
    "Monthly Budget",
    "Monthly Spent",
    "Monthly Remaining",
    "Monthly Utilization %",
    "Quarterly Budget",
    "Quarterly Spent",
    "Quarterly Remaining",
    "Quarterly Utilization %",
    "Annual Budget",
    "Annual Spent",
    "Annual Remaining",
    "Annual Utilization %",
    "Category Caps",
    "Claim Count",
    "Last Claim Date",
]

SUMMARY_HEADERS = [
    "Employee Name",
    "Email",
    "Mobile",
    "Division",
    "Location",
    "Document No.",
    "Invoice Date",
    "Expense Type",
    "Document Type",
    "Line Item",
    "Qty",
    "Line Amount",
    "Currency",
    "Ledger Code",
    "Ledger Name",
    "Document Status",
    "Evaluation Status",
]


@dataclass(frozen=True)
class TeamExpenseExcelExport:
    xlsx_bytes: bytes
    filename: str
    data_rows: int


def _cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _write_title_block(ws: Worksheet, title: str, subtitle: str, col_count: int) -> int:
    """Return the 1-based header row index after title + subtitle + spacer."""
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(col_count, 1))
    title_cell = ws.cell(row=1, column=1, value=title)
    title_cell.fill = TITLE_FILL
    title_cell.font = TITLE_FONT
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(col_count, 1))
    sub_cell = ws.cell(row=2, column=1, value=subtitle)
    sub_cell.font = SUBTITLE_FONT
    sub_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 28

    # Spacer row
    return 4


def _write_header_row(ws: Worksheet, headers: Sequence[str], header_row: int) -> None:
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[header_row].height = 30
    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(len(headers))}{header_row}"
    )


def _autosize(ws: Worksheet, *, max_width: int = 36) -> None:
    for col_idx in range(1, ws.max_column + 1):
        letter = get_column_letter(col_idx)
        max_len = 0
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, min(len(str(cell.value)), 60))
        ws.column_dimensions[letter].width = min(max(max_len + 2, 12), max_width)


def _append_data_rows(
    ws: Worksheet,
    *,
    start_row: int,
    rows: Sequence[Sequence[Any]],
) -> int:
    row_idx = start_row
    for values in rows:
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col, value=_cell_value(value))
            cell.font = BODY_FONT
            if row_idx % 2 == 0:
                cell.fill = ZEBRA_FILL
        row_idx += 1
    return row_idx - start_row


def _advance_values(row: EmployeeAdvanceSettlementRow) -> list[Any]:
    return [
        row.employee_id,
        row.name,
        row.role,
        row.email,
        row.whatsapp_number,
        row.whatsapp_number_2,
        row.viber_number or "",
        row.date_of_joining,
        row.department,
        row.division,
        row.location,
        row.supervisor_1,
        row.supervisor_2,
        row.bank_name,
        row.bank_account_name,
        row.bank_account_number,
        row.bank_bsb,
        row.bank_swift,
        row.bank_iban,
        row.advance_parent_ledger,
        row.advance_sub_ledger,
        row.status,
        row.claim_count,
        row.last_claim,
        row.claim_ytd_spent,
        row.advance_ledger_balance,
        row.pending_against_advance,
        row.available_advance,
    ]


def _budget_values(row: EmployeeBudgetUtilizationRow) -> list[Any]:
    return [
        row.employee_id,
        row.name,
        row.role,
        row.email,
        row.whatsapp_number,
        row.whatsapp_number_2,
        row.viber_number or "",
        row.date_of_joining,
        row.department,
        row.division,
        row.location,
        row.supervisor_1,
        row.supervisor_2,
        row.bank_name,
        row.bank_account_name,
        row.bank_account_number,
        row.bank_bsb,
        row.bank_swift,
        row.bank_iban,
        row.status,
        row.budget_monthly,
        row.mtd_spent,
        row.monthly_remaining if row.monthly_remaining is not None else "",
        row.monthly_utilization_pct if row.monthly_utilization_pct is not None else "",
        row.budget_quarterly,
        row.qtd_spent,
        row.quarterly_remaining if row.quarterly_remaining is not None else "",
        row.quarterly_utilization_pct if row.quarterly_utilization_pct is not None else "",
        row.budget_annual,
        row.ytd_spent,
        row.annual_remaining if row.annual_remaining is not None else "",
        row.annual_utilization_pct if row.annual_utilization_pct is not None else "",
        row.category_caps,
        row.claim_count,
        row.last_claim,
    ]


def _kind_label(kind: str) -> str:
    mapping = {
        "advance_requisition": "Advance requisition",
        "expense_against_advance": "Expense against advance",
        "expense_claim": "Expense claim",
    }
    return mapping.get((kind or "").strip(), kind or "")


def _status_label(status: str) -> str:
    token = (status or "").strip()
    if not token:
        return ""
    return token.replace("_", " ").title()


def _summary_values(row: EmployeeExpenseSummaryRow) -> list[Any]:
    return [
        row.employee_name,
        row.employee_email,
        row.mobile,
        row.division,
        row.location,
        row.document_no,
        row.invoice_date.isoformat() if row.invoice_date else "",
        _kind_label(row.team_expense_kind),
        row.document_type_code,
        row.line_description,
        row.line_qty,
        row.line_amount,
        row.currency,
        row.ledger_code,
        row.ledger_name,
        _status_label(row.status),
        row.evaluation_status,
    ]


def _slug_filename(prefix: str, tenant_slug: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", (tenant_slug or "tenant").strip()) or "tenant"
    return f"{prefix}_{safe}.xlsx"


def _write_sheet(
    ws: Worksheet,
    *,
    title: str,
    subtitle: str,
    headers: Sequence[str],
    data_rows: Sequence[Sequence[Any]],
) -> int:
    header_row = _write_title_block(ws, title, subtitle, len(headers))
    _write_header_row(ws, headers, header_row)
    count = _append_data_rows(ws, start_row=header_row + 1, rows=data_rows)
    if count > 0:
        last = header_row + count
        ws.auto_filter.ref = (
            f"A{header_row}:{get_column_letter(len(headers))}{last}"
        )
    _autosize(ws)
    ws.sheet_view.showGridLines = False
    return count


async def build_team_expense_excel_export(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    report: str,
    tenant_slug: str = "tenant",
    date_from: date | None = None,
    date_to: date | None = None,
) -> TeamExpenseExcelExport:
    """
    Build a single-sheet styled workbook for one TE report kind.

    report: advance-settlement | budget-utilization | expense-summary
    """
    wb = Workbook()
    # remove default sheet; we'll create named sheets
    default = wb.active
    wb.remove(default)

    if report == "advance-settlement":
        rows = await build_advance_settlement_rows(session, tenant_id)
        ws = wb.create_sheet(SHEET_ADVANCE)
        count = _write_sheet(
            ws,
            title="Employee Advance Settlement",
            subtitle=(
                "Live Staff Advance balances by employee. "
                "Ledger = journal outstanding; Pending = open against-advance claims; "
                "Available = ledger − pending. Claim YTD is claim spend only (not advances)."
            ),
            headers=ADVANCE_HEADERS,
            data_rows=[_advance_values(r) for r in rows],
        )
        filename = _slug_filename("employee_advance_settlement", tenant_slug)
    elif report == "budget-utilization":
        rows = await build_budget_utilization_rows(session, tenant_id)
        ws = wb.create_sheet(SHEET_BUDGET)
        count = _write_sheet(
            ws,
            title="Employee Budget Utilization",
            subtitle=(
                "Employee master budget caps vs MTD / QTD / YTD claim spend counters. "
                "Advances do not count toward spend. Utilization blank when cap is zero."
            ),
            headers=BUDGET_HEADERS,
            data_rows=[_budget_values(r) for r in rows],
        )
        filename = _slug_filename("employee_budget_utilization", tenant_slug)
    elif report == "expense-summary":
        rows = await build_employee_expense_summary_rows(
            session, tenant_id, date_from=date_from, date_to=date_to
        )
        period = "All dates"
        if date_from and date_to:
            period = f"{date_from.isoformat()} to {date_to.isoformat()}"
        elif date_from:
            period = f"From {date_from.isoformat()}"
        elif date_to:
            period = f"Through {date_to.isoformat()}"
        ws = wb.create_sheet(SHEET_SUMMARY)
        count = _write_sheet(
            ws,
            title="Employee Expense Summary",
            subtitle=(
                f"Team Expenses line items with employee, ledger, and status. Period: {period}."
            ),
            headers=SUMMARY_HEADERS,
            data_rows=[_summary_values(r) for r in rows],
        )
        filename = _slug_filename("employee_expense_summary", tenant_slug)
    else:
        raise ValueError(f"Unknown team expense report: {report}")

    buf = io.BytesIO()
    wb.save(buf)
    return TeamExpenseExcelExport(
        xlsx_bytes=buf.getvalue(),
        filename=filename,
        data_rows=count,
    )
