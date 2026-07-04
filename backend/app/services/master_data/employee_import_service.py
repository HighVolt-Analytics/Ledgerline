"""Bulk employee master import from reviewed CSV / Excel templates."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_master import EmployeeMasterRecord
from app.schemas.rule_book_config import EmployeeBudget
from app.services.master_data.master_data_service import (
    _new_master_id,
    ensure_masters_imported,
    get_employee_master_by_email,
    sync_masters_to_config_file,
)

EmployeeImportMode = Literal["register", "payment"]

_MAX_IMPORT_ROWS = 500

_REGISTER_FIELDS = ("name", "email", "whatsapp_number", "role", "status")
_PAYMENT_FIELDS = (
    "email",
    "bsb",
    "account_number",
    "account_name",
    "bank_name",
    "budget_monthly",
    "budget_quarterly",
    "budget_annual",
    "status",
)

_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "full name", "employee name", "display name"),
    "email": ("email", "work email", "e-mail", "corporate email", "work e-mail"),
    "whatsapp_number": (
        "whatsapp_number",
        "whatsapp",
        "mobile",
        "phone",
        "cell",
        "work mobile",
        "whatsapp number",
        "whatsapp / mobile",
    ),
    "role": ("role", "department", "job title", "title", "dept", "role / department"),
    "status": ("status", "employment status", "active"),
    "bsb": ("bsb", "bank bsb"),
    "account_number": ("account_number", "account number", "bank account", "account no"),
    "account_name": ("account_name", "account name", "bank account name"),
    "bank_name": ("bank_name", "bank name", "bank"),
    "budget_monthly": (
        "budget_monthly",
        "monthly budget",
        "budget monthly",
    ),
    "budget_quarterly": (
        "budget_quarterly",
        "quarterly budget",
        "budget quarterly",
    ),
    "budget_annual": (
        "budget_annual",
        "annual budget",
        "budget annual",
        "yearly budget",
    ),
}

_TEMPLATE_BRAND = "1F6E7A"
_TEMPLATE_HEADER_FILL = PatternFill("solid", fgColor=_TEMPLATE_BRAND)
_TEMPLATE_HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
_TEMPLATE_TITLE_FONT = Font(size=16, bold=True, color=_TEMPLATE_BRAND)
_TEMPLATE_SUBTITLE_FONT = Font(size=10, color="666666")
_TEMPLATE_NOTE_FONT = Font(size=9, italic=True, color="888888")
_TEMPLATE_EXAMPLE_FILL = PatternFill("solid", fgColor="F4F7F8")
_TEMPLATE_BORDER = Border(
    left=Side(style="thin", color="D0D7DE"),
    right=Side(style="thin", color="D0D7DE"),
    top=Side(style="thin", color="D0D7DE"),
    bottom=Side(style="thin", color="D0D7DE"),
)

_REGISTER_TEMPLATE_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("name", "Full name *", 24),
    ("email", "Work email *", 30),
    ("whatsapp_number", "WhatsApp / mobile", 18),
    ("role", "Role / department", 20),
    ("status", "Status", 20),
)

_PAYMENT_TEMPLATE_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("email", "Work email *", 30),
    ("bsb", "BSB", 12),
    ("account_number", "Account number", 16),
    ("account_name", "Account name", 22),
    ("bank_name", "Bank name", 22),
    ("budget_monthly", "Monthly budget", 18),
    ("budget_quarterly", "Quarterly budget", 20),
    ("budget_annual", "Annual budget", 18),
    ("status", "Status", 20),
)

_STATUS_OPTIONS = '"Active,Pending verification,Suspended"'
_TEMPLATE_DATA_ROWS = 50


@dataclass
class EmployeeImportRowError:
    row_number: int
    email: str | None
    message: str


@dataclass
class EmployeeImportRowPreview:
    row_number: int
    email: str
    name: str | None
    action: Literal["create", "update", "skip"]
    detail: str


@dataclass
class EmployeeImportResult:
    mode: EmployeeImportMode
    dry_run: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[EmployeeImportRowError] = field(default_factory=list)
    previews: list[EmployeeImportRowPreview] = field(default_factory=list)


def _normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (value or "").strip().lower())


def _map_headers(headers: list[str], fields: tuple[str, ...]) -> dict[str, str]:
    normalized = {_normalize_header(header): header for header in headers if header.strip()}
    mapping: dict[str, str] = {}
    for field_name in fields:
        aliases = _HEADER_ALIASES.get(field_name, (field_name,))
        for alias in aliases:
            key = _normalize_header(alias)
            if key in normalized:
                mapping[field_name] = normalized[key]
                break
    return mapping


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_rows_from_csv(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV file has no header row")
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not any(_cell_str(v) for v in raw.values()):
            continue
        rows.append({k: _cell_str(v) for k, v in raw.items() if k})
    return rows


def _normalize_header(value: str) -> str:
    cleaned = re.sub(r"[\s_\-]+", " ", (value or "").strip().lower())
    return cleaned.rstrip(" *").strip()


def _detect_template_fields(headers: list[str]) -> tuple[str, ...] | None:
    register_map = _map_headers(headers, _REGISTER_FIELDS)
    if "name" in register_map and "email" in register_map:
        return _REGISTER_FIELDS
    payment_map = _map_headers(headers, _PAYMENT_FIELDS)
    if "email" in payment_map:
        return _PAYMENT_FIELDS
    return None


def _find_header_row_in_sheet(sheet) -> tuple[int, list[str]] | None:
    for row_idx, cells in enumerate(sheet.iter_rows(min_row=1, max_row=25, values_only=True), start=1):
        headers = [_cell_str(cell) for cell in cells]
        if not any(headers):
            continue
        if _detect_template_fields(headers):
            return row_idx, headers
    return None


def _parse_rows_from_xlsx(data: bytes) -> list[dict[str, str]]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    header_info: tuple[int, list[str], Any] | None = None

    for sheet in workbook.worksheets:
        found = _find_header_row_in_sheet(sheet)
        if found:
            header_info = (found[0], found[1], sheet)
            break

    if not header_info:
        raise ValueError("Excel file has no recognisable header row")

    header_row_idx, headers, sheet = header_info
    rows: list[dict[str, str]] = []
    for cells in sheet.iter_rows(min_row=header_row_idx + 1, values_only=True):
        values = [_cell_str(cell) for cell in cells]
        if not any(values):
            continue
        row = {
            headers[i]: values[i] if i < len(values) else ""
            for i in range(len(headers))
            if headers[i]
        }
        rows.append(row)
    return rows


def parse_employee_import_file(data: bytes, filename: str) -> list[dict[str, str]]:
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        rows = _parse_rows_from_csv(data)
    elif lower.endswith(".xlsx"):
        rows = _parse_rows_from_xlsx(data)
    else:
        raise ValueError("Accepted formats: .csv, .xlsx")
    if len(rows) > _MAX_IMPORT_ROWS:
        raise ValueError(f"Maximum {_MAX_IMPORT_ROWS} data rows per import")
    return rows


def _normalize_status(raw: str, *, default: str) -> str:
    token = (raw or "").strip().lower()
    if not token:
        return default
    if token in {"y", "yes", "true", "1", "active"}:
        return "Active"
    if "suspend" in token or token in {"n", "no", "false", "0", "inactive", "terminated"}:
        return "Suspended"
    if "pending" in token:
        return "Pending verification"
    return raw.strip()


def _parse_budget_amount(raw: str) -> float | None:
    cleaned = (raw or "").strip().replace(",", "")
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _extract_register_row(
    raw: dict[str, str],
    header_map: dict[str, str],
) -> tuple[dict[str, str] | None, str | None]:
    def get(field: str) -> str:
        header = header_map.get(field)
        if not header:
            return ""
        return _cell_str(raw.get(header, ""))

    name = get("name")
    email = get("email").lower()
    if not name:
        return None, "name is required"
    if not email or "@" not in email:
        return None, "valid email is required"
    return {
        "name": name,
        "email": email,
        "whatsapp_number": get("whatsapp_number"),
        "role": get("role"),
        "status": _normalize_status(get("status"), default="Pending verification"),
    }, None


def _extract_payment_row(
    raw: dict[str, str],
    header_map: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    def get(field: str) -> str:
        header = header_map.get(field)
        if not header:
            return ""
        return _cell_str(raw.get(header, ""))

    email = get("email").lower()
    if not email or "@" not in email:
        return None, "valid email is required"

    bank_fields = {
        "bsb": get("bsb") or None,
        "account_number": get("account_number"),
        "account_name": get("account_name"),
        "bank_name": get("bank_name"),
    }
    has_bank = any(_cell_str(v) for v in bank_fields.values() if v is not None)

    budget_fields = {
        "monthly": _parse_budget_amount(get("budget_monthly")),
        "quarterly": _parse_budget_amount(get("budget_quarterly")),
        "annual": _parse_budget_amount(get("budget_annual")),
    }
    has_budget = any(value is not None for value in budget_fields.values())
    status_raw = get("status")

    if not has_bank and not has_budget and not status_raw:
        return None, "no payment fields to update"

    return {
        "email": email,
        "bank": bank_fields if has_bank else None,
        "budget": budget_fields if has_budget else None,
        "status": _normalize_status(status_raw, default="") if status_raw else None,
    }, None


def _apply_cell_border(ws, row: int, col: int) -> None:
    ws.cell(row=row, column=col).border = _TEMPLATE_BORDER


def _autosize_template_columns(ws, columns: tuple[tuple[str, str, int], ...]) -> None:
    for idx, (_field, _label, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


def _write_instructions_sheet(ws, *, mode: EmployeeImportMode) -> None:
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 72

    title = "Employee register import" if mode == "register" else "Employee payment import"
    ws["A1"] = title
    ws["A1"].font = _TEMPLATE_TITLE_FONT
    ws.merge_cells("A1:B1")

    ws["A2"] = "LedgerLink rule book · bulk import template"
    ws["A2"].font = _TEMPLATE_SUBTITLE_FONT
    ws.merge_cells("A2:B2")

    if mode == "register":
        rows = [
            ("Purpose", "Add or update employee identity for team expense claims."),
            ("Required", "Full name and work email on every row."),
            ("Matching", "Rows are matched by work email (case-insensitive)."),
            ("WhatsApp", "Include country code, e.g. +61412345678."),
            ("Status", "Active, Pending verification, or Suspended."),
            ("Default", "Leave status blank for Pending verification."),
            ("Limits", f"Maximum {_MAX_IMPORT_ROWS} data rows per upload."),
            ("Workflow", "1. Fill the Employee data sheet  2. Review import  3. Confirm upload"),
        ]
        example_headers = [label for _field, label, _width in _REGISTER_TEMPLATE_COLUMNS]
        example_values = [
            "Jane Smith",
            "jane.smith@company.com",
            "+61412345678",
            "Finance",
            "Pending verification",
        ]
    else:
        rows = [
            ("Purpose", "Update bank details, budgets, and status for existing employees."),
            ("Required", "Work email on every row; employee must already exist in the register."),
            ("Matching", "Rows are matched by work email (case-insensitive)."),
            ("Bank", "BSB and account number are required before reimbursement."),
            ("Budget", "Leave budget cells empty for no cap. Enter 0 for unlimited."),
            ("Status", "Set Active after finance verifies bank details."),
            ("Limits", f"Maximum {_MAX_IMPORT_ROWS} data rows per upload."),
            ("Workflow", "1. Fill the Employee data sheet  2. Review import  3. Confirm upload"),
        ]
        example_headers = [label for _field, label, _width in _PAYMENT_TEMPLATE_COLUMNS]
        example_values = [
            "jane.smith@company.com",
            "062-001",
            "12345678",
            "Jane Smith",
            "Commonwealth Bank",
            "2000",
            "5500",
            "20000",
            "Active",
        ]

    start = 4
    for offset, (label, value) in enumerate(rows):
        row = start + offset
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=10)
        ws.cell(row=row, column=2, value=value).font = Font(size=10)
        ws.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")

    example_row = start + len(rows) + 2
    ws.cell(row=example_row, column=1, value="Example row").font = Font(bold=True, size=10)
    ws.merge_cells(start_row=example_row, start_column=1, end_row=example_row, end_column=2)

    header_row = example_row + 1
    for col, header in enumerate(example_headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.fill = _TEMPLATE_HEADER_FILL
        cell.font = _TEMPLATE_HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")

    value_row = header_row + 1
    for col, value in enumerate(example_values, start=1):
        cell = ws.cell(row=value_row, column=col, value=value)
        cell.fill = _TEMPLATE_EXAMPLE_FILL
        cell.font = Font(size=10, italic=True)

    note_row = value_row + 2
    ws.cell(
        row=note_row,
        column=1,
        value="Enter your data on the Employee data sheet. Do not rename header cells.",
    ).font = _TEMPLATE_NOTE_FONT
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=2)


def _write_data_sheet(ws, *, mode: EmployeeImportMode) -> None:
    columns = _REGISTER_TEMPLATE_COLUMNS if mode == "register" else _PAYMENT_TEMPLATE_COLUMNS
    col_count = len(columns)
    last_col = get_column_letter(col_count)

    title = "Employee register" if mode == "register" else "Employee payment details"
    ws["A1"] = title
    ws["A1"].font = _TEMPLATE_TITLE_FONT
    ws.merge_cells(f"A1:{last_col}1")

    subtitle = (
        "Required columns are marked *. Delete any sample rows before upload."
        if mode == "register"
        else "Email must match an existing employee. Delete any sample rows before upload."
    )
    ws["A2"] = subtitle
    ws["A2"].font = _TEMPLATE_SUBTITLE_FONT
    ws.merge_cells(f"A2:{last_col}2")

    header_row = 4
    for col, (_field, label, _width) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=col, value=label)
        cell.fill = _TEMPLATE_HEADER_FILL
        cell.font = _TEMPLATE_HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        _apply_cell_border(ws, header_row, col)

    status_col = next(
        (idx for idx, (field, _label, _width) in enumerate(columns, start=1) if field == "status"),
        None,
    )
    if status_col:
        status_letter = get_column_letter(status_col)
        validation = DataValidation(
            type="list",
            formula1=_STATUS_OPTIONS,
            allow_blank=True,
            showDropDown=True,
        )
        validation.error = "Choose Active, Pending verification, or Suspended"
        validation.errorTitle = "Invalid status"
        first_data_row = header_row + 1
        last_data_row = header_row + _TEMPLATE_DATA_ROWS
        validation.add(f"{status_letter}{first_data_row}:{status_letter}{last_data_row}")
        ws.add_data_validation(validation)

    first_data_row = header_row + 1
    last_data_row = header_row + _TEMPLATE_DATA_ROWS
    for row in range(first_data_row, last_data_row + 1):
        for col in range(1, col_count + 1):
            _apply_cell_border(ws, row, col)
            ws.cell(row=row, column=col).alignment = Alignment(vertical="center")

    ws.freeze_panes = ws.cell(row=first_data_row, column=1)
    ws.row_dimensions[header_row].height = 28
    _autosize_template_columns(ws, columns)


def build_import_template(mode: EmployeeImportMode) -> bytes:
    workbook = Workbook()
    data_sheet = workbook.active
    data_sheet.title = "Employee data"
    _write_data_sheet(data_sheet, mode=mode)

    instructions = workbook.create_sheet("Instructions")
    _write_instructions_sheet(instructions, mode=mode)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def import_employee_masters(
    db: AsyncSession,
    tenant_id: int,
    *,
    mode: EmployeeImportMode,
    rows: list[dict[str, str]],
    dry_run: bool = False,
) -> EmployeeImportResult:
    await ensure_masters_imported(db, tenant_id)
    fields = _REGISTER_FIELDS if mode == "register" else _PAYMENT_FIELDS
    if not rows:
        raise ValueError("No data rows found")

    first_keys = list(rows[0].keys())
    header_map = _map_headers(first_keys, fields)
    if mode == "register":
        if "name" not in header_map or "email" not in header_map:
            raise ValueError("Register file must include name and email columns")
    elif "email" not in header_map:
        raise ValueError("Payment file must include an email column")

    result = EmployeeImportResult(mode=mode, dry_run=dry_run)

    for index, raw in enumerate(rows, start=2):
        if mode == "register":
            parsed, error = _extract_register_row(raw, header_map)
        else:
            parsed, error = _extract_payment_row(raw, header_map)

        if error:
            result.errors.append(
                EmployeeImportRowError(
                    row_number=index,
                    email=(parsed or {}).get("email") if parsed else None,
                    message=error,
                )
            )
            result.skipped += 1
            continue

        assert parsed is not None
        email = parsed["email"]
        existing = await get_employee_master_by_email(db, tenant_id, email)

        if mode == "register":
            preview_name = parsed["name"]
            if existing:
                if not dry_run:
                    existing.name = parsed["name"]
                    if parsed["whatsapp_number"]:
                        existing.whatsapp_number = parsed["whatsapp_number"]
                    if parsed["role"]:
                        existing.role = parsed["role"]
                    if parsed["status"]:
                        existing.status = parsed["status"]
                result.updated += 1
                result.previews.append(
                    EmployeeImportRowPreview(
                        row_number=index,
                        email=email,
                        name=preview_name,
                        action="update",
                        detail="Updated identity fields",
                    )
                )
            else:
                if not dry_run:
                    db.add(
                        EmployeeMasterRecord(
                            tenant_id=tenant_id,
                            master_id=_new_master_id("em", parsed["name"]),
                            name=parsed["name"],
                            role=parsed.get("role") or "",
                            email=email,
                            whatsapp_number=parsed.get("whatsapp_number") or "",
                            viber_number=None,
                            bank={},
                            budget=EmployeeBudget().model_dump(),
                            status=parsed.get("status") or "Pending verification",
                        )
                    )
                result.created += 1
                result.previews.append(
                    EmployeeImportRowPreview(
                        row_number=index,
                        email=email,
                        name=preview_name,
                        action="create",
                        detail="New employee",
                    )
                )
            continue

        if existing is None:
            result.errors.append(
                EmployeeImportRowError(
                    row_number=index,
                    email=email,
                    message="no employee found for this email — import register file first",
                )
            )
            result.skipped += 1
            continue

        if not dry_run:
            bank_patch = parsed.get("bank")
            if bank_patch:
                merged = dict(existing.bank or {})
                for key, value in bank_patch.items():
                    if value is not None and str(value).strip():
                        merged[key] = str(value).strip()
                existing.bank = merged

            budget_patch = parsed.get("budget")
            if budget_patch:
                merged_budget = dict(existing.budget or EmployeeBudget().model_dump())
                for period, value in budget_patch.items():
                    if value is not None:
                        merged_budget[period] = value
                existing.budget = merged_budget

            status = parsed.get("status")
            if status:
                existing.status = status

        result.updated += 1
        result.previews.append(
            EmployeeImportRowPreview(
                row_number=index,
                email=email,
                name=existing.name,
                action="update",
                detail="Updated payment fields",
            )
        )

    if not dry_run and (result.created or result.updated):
        await db.flush()
        await sync_masters_to_config_file(db, tenant_id)

    return result
