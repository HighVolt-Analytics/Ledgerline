"""Team expense finance reports — advance settlement, budget utilization, expense summary."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.master_data import EmployeeMasterResponse
from app.schemas.rule_book_config import (
    BankDetails,
    EmployeeBudget,
)
from app.schemas.team_expense_reports import (
    EmployeeAdvanceSettlementRow,
    EmployeeBudgetUtilizationRow,
    EmployeeExpenseSummaryRow,
)
from app.services.dossier.document_ref_service import display_document_ref
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM, load_config_for_tenant
from app.services.master_data.master_data_service import list_employee_masters
from app.services.purchase.team_expense_advance_service import (
    employee_advance_activity_by_ids,
    employee_advance_balances_by_ids,
    pending_claim_advance_reservation,
)
from app.services.purchase.team_expense_spend_service import (
    employee_period_spend,
    normalize_employee_email,
)
from app.services.purchase.team_expense_validator import find_employee_by_sender

_SUSPENSE_ACCOUNT = "Suspense Account"


def _effective_invoice_date():
    return func.coalesce(Invoice.invoice_date, func.date(Invoice.created_at))


def _bank_fields(employee: EmployeeMasterResponse) -> dict[str, str]:
    bank = employee.bank if isinstance(employee.bank, BankDetails) else BankDetails()
    return {
        "bank_name": bank.bank_name or "",
        "bank_account_name": bank.account_name or "",
        "bank_account_number": bank.account_number or "",
        "bank_bsb": bank.bsb or "",
        "bank_swift": bank.swift or "",
        "bank_iban": bank.iban or "",
    }


def _budget(employee: EmployeeMasterResponse) -> EmployeeBudget:
    limits = getattr(employee, "spending_limits", None) or getattr(employee, "budget", None)
    if isinstance(limits, EmployeeBudget):
        return limits
    return EmployeeBudget.model_validate(limits or {})


def _category_caps_text(budget: EmployeeBudget) -> str:
    parts: list[str] = []
    for cap in budget.categories or []:
        ledger = (cap.ledger or "").strip()
        if not ledger:
            continue
        parts.append(f"{ledger}:{cap.cap:g}")
    return "; ".join(parts)


def _remaining(cap: float, spent: float) -> float | None:
    if cap is None or float(cap) <= 0:
        return None
    return max(0.0, float(cap) - float(spent or 0))


def _utilization_pct(cap: float, spent: float) -> float | None:
    if cap is None or float(cap) <= 0:
        return None
    return round((float(spent or 0) / float(cap)) * 100.0, 2)


def _money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


async def build_advance_settlement_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[EmployeeAdvanceSettlementRow]:
    config = await load_config_for_tenant(session, tenant_id)
    employees = await list_employee_masters(
        session, tenant_id, include_advance_balances=False
    )
    activity = await employee_advance_activity_by_ids(
        session, tenant_id, config, employees
    )

    rows: list[EmployeeAdvanceSettlementRow] = []
    for emp in employees:
        emp_id = (emp.id or "").strip()
        taken, used, ledger = activity.get(
            emp_id, (Decimal("0"), Decimal("0"), Decimal("0"))
        )
        pending = await pending_claim_advance_reservation(session, tenant_id, emp)
        available = ledger - pending
        if available < 0:
            available = Decimal("0")
        rows.append(
            EmployeeAdvanceSettlementRow(
                employee_id=emp_id,
                name=emp.name or "",
                role=emp.role or "",
                email=emp.email or "",
                whatsapp_number=emp.whatsapp_number or "",
                whatsapp_number_2=emp.whatsapp_number_2 or "",
                viber_number=emp.viber_number,
                date_of_joining=emp.date_of_joining or "",
                department=emp.department or "",
                location=emp.location or "",
                division=emp.division or "",
                supervisor_1=emp.supervisor_1 or "",
                supervisor_2=emp.supervisor_2 or "",
                **_bank_fields(emp),
                advance_parent_ledger=emp.advance_parent_ledger or "",
                advance_sub_ledger=emp.advance_sub_ledger or "",
                status=emp.status or "",
                claim_count=int(emp.claim_count or 0),
                last_claim=emp.last_claim or "",
                claim_ytd_spent=float(emp.ytd_spent or 0),
                advance_ledger_balance=ledger,
                advance_taken=taken,
                advance_used=used,
                pending_against_advance=pending,
                available_advance=available,
            )
        )
    return rows


async def build_budget_utilization_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[EmployeeBudgetUtilizationRow]:
    """Employee spending-limit utilization from computed period spend (invoice truth).

    Accrual columns (mtd/qtd/ytd + remaining) exclude advances. Cash columns reserve
    outstanding Staff Advance float against the same period limits so managers see
    how much of the envelope is still free after cash already paid out as advances.
    """
    config = await load_config_for_tenant(session, tenant_id)
    employees = await list_employee_masters(
        session, tenant_id, include_advance_balances=False
    )
    balances = await employee_advance_balances_by_ids(
        session, tenant_id, config, employees
    )
    rows: list[EmployeeBudgetUtilizationRow] = []
    for emp in employees:
        budget = _budget(emp)
        email = normalize_employee_email(emp.email)
        if email:
            spend = await employee_period_spend(session, tenant_id, email)
            mtd, qtd, ytd = spend.mtd, spend.qtd, spend.ytd
        else:
            mtd = float(emp.mtd_spent or 0)
            qtd = float(emp.qtd_spent or 0)
            ytd = float(emp.ytd_spent or 0)
        emp_id = (emp.id or "").strip()
        advance_float = float(balances.get(emp_id, Decimal("0")) or 0)
        if advance_float < 0:
            advance_float = 0.0
        m_cash = mtd + advance_float
        q_cash = qtd + advance_float
        y_cash = ytd + advance_float
        rows.append(
            EmployeeBudgetUtilizationRow(
                employee_id=emp_id,
                name=emp.name or "",
                role=emp.role or "",
                email=emp.email or "",
                whatsapp_number=emp.whatsapp_number or "",
                whatsapp_number_2=emp.whatsapp_number_2 or "",
                viber_number=emp.viber_number,
                date_of_joining=emp.date_of_joining or "",
                department=emp.department or "",
                location=emp.location or "",
                division=emp.division or "",
                supervisor_1=emp.supervisor_1 or "",
                supervisor_2=emp.supervisor_2 or "",
                **_bank_fields(emp),
                status=emp.status or "",
                budget_monthly=float(budget.monthly or 0),
                budget_quarterly=float(budget.quarterly or 0),
                budget_annual=float(budget.annual or 0),
                category_caps=_category_caps_text(budget),
                mtd_spent=mtd,
                qtd_spent=qtd,
                ytd_spent=ytd,
                claim_count=int(emp.claim_count or 0),
                last_claim=emp.last_claim or "",
                monthly_remaining=_remaining(budget.monthly, mtd),
                quarterly_remaining=_remaining(budget.quarterly, qtd),
                annual_remaining=_remaining(budget.annual, ytd),
                monthly_utilization_pct=_utilization_pct(budget.monthly, mtd),
                quarterly_utilization_pct=_utilization_pct(budget.quarterly, qtd),
                annual_utilization_pct=_utilization_pct(budget.annual, ytd),
                advance_float=advance_float,
                monthly_cash_committed=m_cash,
                quarterly_cash_committed=q_cash,
                annual_cash_committed=y_cash,
                monthly_cash_remaining=_remaining(budget.monthly, m_cash),
                quarterly_cash_remaining=_remaining(budget.quarterly, q_cash),
                annual_cash_remaining=_remaining(budget.annual, y_cash),
                monthly_cash_utilization_pct=_utilization_pct(budget.monthly, m_cash),
                quarterly_cash_utilization_pct=_utilization_pct(budget.quarterly, q_cash),
                annual_cash_utilization_pct=_utilization_pct(budget.annual, y_cash),
            )
        )
    return rows


def _invoice_ledger(invoice: Invoice) -> tuple[str, str]:
    code = (invoice.account_code or "").strip()
    name = (invoice.account_name or "").strip() or _SUSPENSE_ACCOUNT
    return code, name


def _status_value(status: Any) -> str:
    if status is None:
        return ""
    return status.value if hasattr(status, "value") else str(status)


async def build_employee_expense_summary_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[EmployeeExpenseSummaryRow]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")

    employees = await list_employee_masters(
        session, tenant_id, include_advance_balances=False
    )
    effective = _effective_invoice_date()
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.route_target == ROUTE_TEAM,
        )
    )
    if date_from is not None:
        stmt = stmt.where(effective >= date_from)
    if date_to is not None:
        stmt = stmt.where(effective <= date_to)
    stmt = stmt.order_by(effective.desc(), Invoice.id.desc())
    invoices = list((await session.execute(stmt)).scalars().unique().all())

    rows: list[EmployeeExpenseSummaryRow] = []
    for invoice in invoices:
        employee = find_employee_by_sender(employees, invoice.email_sender)
        emp_name = employee.name if employee else ""
        emp_email = employee.email if employee else ""
        mobile = (employee.whatsapp_number if employee else "") or ""
        division = employee.division if employee else ""
        location = employee.location if employee else ""
        doc_no = display_document_ref(invoice)
        if not (doc_no or "").strip():
            doc_no = (invoice.invoice_no or "").strip() or f"INV-{invoice.id}"
        ledger_code, ledger_name = _invoice_ledger(invoice)
        kind = (invoice.team_expense_kind or "").strip()
        dt_code = (invoice.document_type_code or "").strip()
        status = _status_value(invoice.status)
        eval_status = (invoice.evaluation_status or "").strip()
        currency = (invoice.currency or "").strip()

        lines = list(invoice.line_items or [])
        if not lines:
            rows.append(
                EmployeeExpenseSummaryRow(
                    employee_name=emp_name,
                    employee_email=emp_email,
                    mobile=mobile,
                    division=division or "",
                    location=location or "",
                    document_no=doc_no,
                    invoice_date=invoice.invoice_date,
                    team_expense_kind=kind,
                    document_type_code=dt_code,
                    line_description=(invoice.vendor or "").strip() or "Header total",
                    line_qty=None,
                    line_amount=invoice.total,
                    ledger_code=ledger_code,
                    ledger_name=ledger_name,
                    status=status,
                    evaluation_status=eval_status,
                    invoice_id=invoice.id,
                    currency=currency,
                )
            )
            continue

        for line in lines:
            line_ledger_name = ledger_name
            line_ledger_code = ledger_code
            sub = (line.sub_ledger or "").strip()
            if sub:
                line_ledger_name = sub
            rows.append(
                EmployeeExpenseSummaryRow(
                    employee_name=emp_name,
                    employee_email=emp_email,
                    mobile=mobile,
                    division=division or "",
                    location=location or "",
                    document_no=doc_no,
                    invoice_date=invoice.invoice_date,
                    team_expense_kind=kind,
                    document_type_code=dt_code,
                    line_description=(line.description or "").strip(),
                    line_qty=line.qty,
                    line_amount=line.amount if line.amount is not None else invoice.total,
                    ledger_code=line_ledger_code,
                    ledger_name=line_ledger_name,
                    status=status,
                    evaluation_status=eval_status,
                    invoice_id=invoice.id,
                    currency=currency,
                )
            )
    return rows
