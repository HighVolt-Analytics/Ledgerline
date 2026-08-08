"""Team expense finance reports — advance settlement, budget utilization, expense summary."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.schemas.master_data import EmployeeMasterResponse
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    BankDetails,
    EmployeeBudget,
)
from app.schemas.team_expense_reports import (
    EmployeeAdvanceDetailRow,
    EmployeeAdvanceSettlementRow,
    EmployeeBudgetUtilizationRow,
    EmployeeExpenseSummaryRow,
    EmployeeMasterReportRow,
    EmployeeSpendDetailRow,
)
from app.services.audit.audit_service import audit_logs_for_invoices
from app.services.dossier.document_ref_service import display_document_ref
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM, load_config_for_tenant
from app.services.master_data.chart_of_accounts_service import (
    account_is_sub_ledger,
    parent_ledger_for_account,
)
from app.services.master_data.department_budget_service import list_department_budgets
from app.services.master_data.master_data_service import list_employee_masters
from app.services.purchase.team_expense_advance_service import (
    employee_advance_account_code,
    employee_advance_activity_by_ids,
    employee_advance_balances_by_ids,
    pending_claim_advance_reservation,
)
from app.services.purchase.team_expense_spend_service import (
    current_period_keys,
    employee_period_spend,
    normalize_employee_email,
    period_bounds,
)
from app.services.purchase.team_expense_validator import (
    find_employee_by_sender,
    resolve_team_expense_employee,
)
from app.services.rule_book.rule_book_mapper import get_team_settlement_account_mapping

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


def _summary_main_and_sub(
    *,
    account_token: str,
    line_sub_ledger: str,
    chart_of_accounts: list,
) -> tuple[str, str]:
    """Resolve Main GL / Sub-Ledger for an expense-summary line."""
    main_gl, header_sub = _resolve_main_and_sub(account_token, chart_of_accounts)
    line_sub = (line_sub_ledger or "").strip()
    if not line_sub:
        return main_gl, header_sub
    if account_is_sub_ledger(line_sub, chart_of_accounts):
        parent = parent_ledger_for_account(line_sub, chart_of_accounts)
        return (parent or main_gl or line_sub), line_sub
    # Line label is not a catalog Sub-GL — keep header Main GL, show line token as Sub.
    return main_gl or line_sub, line_sub


async def build_employee_expense_summary_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[EmployeeExpenseSummaryRow]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")

    config = await load_config_for_tenant(session, tenant_id)
    coa = list(config.chart_of_accounts or [])
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
        employee = resolve_team_expense_employee(
            employees,
            employee_email=invoice.employee_email,
            email_sender=invoice.email_sender,
        )
        emp_id = (employee.id if employee else "") or ""
        emp_name = employee.name if employee else ""
        emp_role = (employee.role if employee else "") or ""
        emp_email = employee.email if employee else ""
        mobile = (employee.whatsapp_number if employee else "") or ""
        department = (employee.department if employee else "") or ""
        division = (employee.division if employee else "") or ""
        location = (employee.location if employee else "") or ""
        doc_no = display_document_ref(invoice)
        if not (doc_no or "").strip():
            doc_no = (invoice.invoice_no or "").strip() or f"INV-{invoice.id}"
        ledger_code, _header_name = _invoice_ledger(invoice)
        account_token = (
            (invoice.account_name or "").strip()
            or (invoice.account_code or "").strip()
            or _SUSPENSE_ACCOUNT
        )
        kind = (invoice.team_expense_kind or "").strip()
        dt_code = (invoice.document_type_code or "").strip()
        status = _status_value(invoice.status)
        eval_status = (invoice.evaluation_status or "").strip()
        currency = (invoice.currency or "").strip()

        def _base_row(
            *,
            line_description: str,
            line_qty: Decimal | None,
            line_amount: Decimal | None,
            line_sub: str,
        ) -> EmployeeExpenseSummaryRow:
            main_gl, sub_ledger = _summary_main_and_sub(
                account_token=account_token,
                line_sub_ledger=line_sub,
                chart_of_accounts=coa,
            )
            return EmployeeExpenseSummaryRow(
                employee_id=emp_id.strip(),
                employee_name=emp_name,
                role=emp_role,
                employee_email=emp_email or "",
                mobile=mobile,
                department=department,
                division=division,
                location=location,
                document_no=doc_no,
                invoice_date=invoice.invoice_date,
                team_expense_kind=kind,
                document_type_code=dt_code,
                line_description=line_description,
                line_qty=line_qty,
                line_amount=line_amount,
                ledger_code=ledger_code,
                main_gl=main_gl,
                sub_ledger=sub_ledger,
                status=status,
                evaluation_status=eval_status,
                invoice_id=invoice.id,
                currency=currency,
            )

        lines = list(invoice.line_items or [])
        if not lines:
            rows.append(
                _base_row(
                    line_description=(invoice.vendor or "").strip() or "Header total",
                    line_qty=None,
                    line_amount=invoice.total,
                    line_sub="",
                )
            )
            continue

        for line in lines:
            amount = line.amount if line.amount is not None else None
            rows.append(
                _base_row(
                    line_description=(line.description or "").strip(),
                    line_qty=line.qty,
                    line_amount=amount,
                    line_sub=(line.sub_ledger or "").strip(),
                )
            )
    return rows


def _master_fields(emp: EmployeeMasterResponse) -> dict[str, Any]:
    bank = _bank_fields(emp)
    return {
        "employee_id": (emp.id or "").strip(),
        "name": emp.name or "",
        "role": emp.role or "",
        "email": emp.email or "",
        "whatsapp_number": emp.whatsapp_number or "",
        "whatsapp_number_2": emp.whatsapp_number_2 or "",
        "viber_number": emp.viber_number,
        "date_of_joining": emp.date_of_joining or "",
        "department": emp.department or "",
        "location": emp.location or "",
        "division": emp.division or "",
        "supervisor_1": emp.supervisor_1 or "",
        "supervisor_2": emp.supervisor_2 or "",
        **bank,
        "advance_parent_ledger": emp.advance_parent_ledger or "",
        "advance_sub_ledger": emp.advance_sub_ledger or "",
        "status": emp.status or "",
    }


def _resolve_main_and_sub(
    account_token: str,
    chart_of_accounts: list,
) -> tuple[str, str]:
    """Return (Main GL, Sub-Ledger) for a posted claim account."""
    token = (account_token or "").strip()
    if not token:
        return _SUSPENSE_ACCOUNT, ""
    parent = parent_ledger_for_account(token, chart_of_accounts)
    if account_is_sub_ledger(token, chart_of_accounts):
        return (parent or token), token
    if parent:
        return parent, ""
    return token, ""


def _budget_index(
    budgets: list[Any],
    period_keys: dict[str, str],
) -> dict[str, float]:
    """Map lowercased GL → allocated for the best current period (annual > quarterly > monthly)."""
    kind_rank = {"annual": 3, "quarterly": 2, "monthly": 1}
    best: dict[str, tuple[int, float]] = {}
    for bud in budgets:
        kind = (bud.period_kind or "").strip().lower()
        if period_keys.get(kind) != (bud.period_key or "").strip():
            continue
        gl = (bud.gl_ledger or "").strip()
        if not gl:
            continue
        rank = kind_rank.get(kind, 0)
        key = gl.lower()
        prev = best.get(key)
        if prev is None or rank > prev[0]:
            best[key] = (rank, float(bud.allocated or 0))
    return {k: v[1] for k, v in best.items()}


def _lookup_sub_gl_budget(
    *,
    main_gl: str,
    sub_ledger: str,
    budget_by_gl: dict[str, float],
) -> float:
    for token in (sub_ledger, main_gl):
        cleaned = (token or "").strip()
        if not cleaned:
            continue
        amount = budget_by_gl.get(cleaned.lower())
        if amount is not None:
            return float(amount)
    return 0.0


async def build_employee_master_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[EmployeeMasterReportRow]:
    employees = await list_employee_masters(
        session, tenant_id, include_advance_balances=False
    )
    return [EmployeeMasterReportRow(**_master_fields(emp)) for emp in employees]


async def build_employee_spend_detail_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    as_of: date | None = None,
) -> list[EmployeeSpendDetailRow]:
    """One row per employee × expense Sub-GL with YTD claim activity."""
    today = as_of or date.today()
    _, _, _, _, y_start, y_end = period_bounds(today)
    y_end = min(y_end, today)
    period_keys = current_period_keys(today)

    config = await load_config_for_tenant(session, tenant_id)
    coa = list(config.chart_of_accounts or [])
    employees = await list_employee_masters(
        session, tenant_id, include_advance_balances=False
    )
    employees_by_email = {
        normalize_employee_email(emp.email): emp
        for emp in employees
        if normalize_employee_email(emp.email)
    }

    budgets = await list_department_budgets(session, tenant_id)
    budget_by_gl = _budget_index(budgets, period_keys)

    settlement = get_team_settlement_account_mapping(config)
    settlement_tokens = {
        t
        for t in {
            (settlement.account_name or "").strip().lower(),
            (settlement.account_code or "").strip().lower(),
        }
        if t
    }

    effective = _effective_invoice_date()
    claim_stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.route_target == ROUTE_TEAM,
            Invoice.status == InvoiceStatus.PROCESSED,
            Invoice.team_expense_kind == TEAM_EXPENSE_KIND_CLAIM,
            effective >= y_start,
            effective <= y_end,
        )
        .order_by(effective.asc(), Invoice.id.asc())
    )
    claims = list((await session.execute(claim_stmt)).scalars().all())
    if not claims:
        return []

    claim_ids = [inv.id for inv in claims]
    cash_by_invoice: dict[int, float] = {inv.id: 0.0 for inv in claims}
    if settlement_tokens:
        cash_stmt = (
            select(
                JournalEntry.invoice_id,
                func.coalesce(func.sum(JournalEntry.credit), 0),
            )
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.invoice_id.in_(claim_ids),
                JournalEntry.entry_type == EntryType.CREDIT,
                or_(
                    func.lower(func.coalesce(JournalEntry.account_name, "")).in_(
                        list(settlement_tokens)
                    ),
                    func.lower(func.coalesce(JournalEntry.account_code, "")).in_(
                        list(settlement_tokens)
                    ),
                ),
            )
            .group_by(JournalEntry.invoice_id)
        )
        for invoice_id, credit_sum in (await session.execute(cash_stmt)).all():
            cash_by_invoice[int(invoice_id)] = float(Decimal(str(credit_sum or 0)))

    # Aggregate by (employee_email, main_gl, sub_ledger)
    agg: dict[tuple[str, str, str], dict[str, Any]] = {}
    for inv in claims:
        emp = resolve_team_expense_employee(
            employees,
            employee_email=inv.employee_email,
            email_sender=inv.email_sender,
        )
        if emp is None:
            continue
        email = normalize_employee_email(emp.email)
        if not email:
            continue
        token = (inv.account_name or "").strip() or (inv.account_code or "").strip()
        main_gl, sub_ledger = _resolve_main_and_sub(token, coa)
        key = (email, main_gl.lower(), (sub_ledger or main_gl).lower())
        bucket = agg.get(key)
        if bucket is None:
            bucket = {
                "email": email,
                "main_gl": main_gl,
                "sub_ledger": sub_ledger or main_gl,
                "spend": 0.0,
                "claims": 0,
                "cash": 0.0,
                "last_claim": None,
            }
            agg[key] = bucket
        amount = float(Decimal(str(inv.total or 0)))
        bucket["spend"] += amount
        bucket["claims"] += 1
        bucket["cash"] += cash_by_invoice.get(inv.id, 0.0)
        claim_day = inv.invoice_date or (
            inv.created_at.date() if getattr(inv, "created_at", None) else None
        )
        if claim_day is not None:
            prev = bucket["last_claim"]
            if prev is None or claim_day > prev:
                bucket["last_claim"] = claim_day

    pending_by_email: dict[str, Decimal] = {}
    period_spend_by_email: dict[str, tuple[float, float, float]] = {}
    rows: list[EmployeeSpendDetailRow] = []
    for bucket in sorted(
        agg.values(),
        key=lambda b: (
            (employees_by_email[b["email"]].name or "").lower(),
            b["main_gl"].lower(),
            b["sub_ledger"].lower(),
        ),
    ):
        emp = employees_by_email[bucket["email"]]
        email = bucket["email"]
        if email not in pending_by_email:
            pending_by_email[email] = await pending_claim_advance_reservation(
                session, tenant_id, emp
            )
        if email not in period_spend_by_email:
            period = await employee_period_spend(
                session, tenant_id, email, as_of=today
            )
            period_spend_by_email[email] = (period.mtd, period.qtd, period.ytd)
        mtd, qtd, ytd_total = period_spend_by_email[email]
        limits = _budget(emp)
        spend = float(bucket["spend"])
        sub_budget = _lookup_sub_gl_budget(
            main_gl=bucket["main_gl"],
            sub_ledger=bucket["sub_ledger"],
            budget_by_gl=budget_by_gl,
        )
        pct = (
            round((spend / sub_budget) * 100.0, 2) if sub_budget > 0 else None
        )
        last = bucket["last_claim"]
        rows.append(
            EmployeeSpendDetailRow(
                **_master_fields(emp),
                main_gl=bucket["main_gl"],
                sub_ledger=bucket["sub_ledger"],
                sub_gl_budget=sub_budget,
                employee_spend_ytd=round(spend, 2),
                pct_of_sub_gl_used=pct,
                claim_count=int(bucket["claims"]),
                advance_pending=pending_by_email[email],
                cash_reimbursed_ytd=round(float(bucket["cash"]), 2),
                last_claim_date=last.isoformat() if last else "",
                budget_monthly=float(limits.monthly or 0),
                budget_quarterly=float(limits.quarterly or 0),
                budget_annual=float(limits.annual or 0),
                mtd_spent=mtd,
                qtd_spent=qtd,
                ytd_spent_total=ytd_total,
                monthly_remaining=_remaining(limits.monthly, mtd),
                quarterly_remaining=_remaining(limits.quarterly, qtd),
                annual_remaining=_remaining(limits.annual, ytd_total),
                monthly_utilization_pct=_utilization_pct(limits.monthly, mtd),
                quarterly_utilization_pct=_utilization_pct(limits.quarterly, qtd),
                annual_utilization_pct=_utilization_pct(limits.annual, ytd_total),
            )
        )
    return rows


def _approval_from_logs(logs: list[Any]) -> tuple[str, str]:
    """Latest invoice_approved actor name/email and date."""
    for entry in logs or []:
        if (getattr(entry, "event", None) or "") != "invoice_approved":
            continue
        detail = getattr(entry, "detail", None) or {}
        if not isinstance(detail, dict):
            detail = {}
        name = str(detail.get("actor_name") or "").strip()
        email = str(detail.get("actor_email") or "").strip()
        approved_by = name or email
        created = getattr(entry, "created_at", None)
        approved_on = ""
        if created is not None:
            approved_on = created.date().isoformat() if hasattr(created, "date") else str(created)[:10]
        return approved_by, approved_on
    return "", ""


async def build_employee_advance_detail_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[EmployeeAdvanceDetailRow]:
    """Movement ledger: one row per advance Took, one row per claim Used."""
    config = await load_config_for_tenant(session, tenant_id)
    employees = await list_employee_masters(
        session, tenant_id, include_advance_balances=False
    )
    if not employees:
        return []

    code_to_emp: dict[str, EmployeeMasterResponse] = {}
    for emp in employees:
        emp_id = (emp.id or "").strip()
        if not emp_id:
            continue
        code = employee_advance_account_code(
            config,
            employee_id=emp_id,
            employee_parent_ledger=emp.advance_parent_ledger or "",
        )
        if code:
            code_to_emp[code] = emp
    if not code_to_emp:
        return []

    settlement = get_team_settlement_account_mapping(config)
    settlement_tokens = {
        t
        for t in {
            (settlement.account_name or "").strip().lower(),
            (settlement.account_code or "").strip().lower(),
        }
        if t
    }

    journal_rows = (
        await session.execute(
            select(JournalEntry)
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.account_code.in_(list(code_to_emp.keys())),
                or_(JournalEntry.debit > 0, JournalEntry.credit > 0),
            )
            .order_by(JournalEntry.date.asc(), JournalEntry.id.asc())
        )
    ).scalars().all()
    if not journal_rows:
        return []

    invoice_ids = sorted({int(j.invoice_id) for j in journal_rows if j.invoice_id})
    invoices: dict[int, Invoice] = {}
    if invoice_ids:
        inv_list = (
            await session.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.id.in_(invoice_ids),
                )
            )
        ).scalars().all()
        invoices = {int(inv.id): inv for inv in inv_list}

    approval_logs = await audit_logs_for_invoices(
        session, invoice_ids, tenant_id=tenant_id
    )

    cash_by_invoice: dict[int, Decimal] = {iid: Decimal("0") for iid in invoice_ids}
    if settlement_tokens and invoice_ids:
        cash_stmt = (
            select(
                JournalEntry.invoice_id,
                func.coalesce(func.sum(JournalEntry.credit), 0),
            )
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.invoice_id.in_(invoice_ids),
                JournalEntry.entry_type == EntryType.CREDIT,
                or_(
                    func.lower(func.coalesce(JournalEntry.account_name, "")).in_(
                        list(settlement_tokens)
                    ),
                    func.lower(func.coalesce(JournalEntry.account_code, "")).in_(
                        list(settlement_tokens)
                    ),
                ),
            )
            .group_by(JournalEntry.invoice_id)
        )
        for invoice_id, credit_sum in (await session.execute(cash_stmt)).all():
            cash_by_invoice[int(invoice_id)] = Decimal(str(credit_sum or 0))

    activity = await employee_advance_activity_by_ids(
        session, tenant_id, config, employees
    )
    pending_by_emp: dict[str, Decimal] = {}
    available_by_emp: dict[str, Decimal] = {}
    for emp in employees:
        emp_id = (emp.id or "").strip()
        if not emp_id:
            continue
        pending = await pending_claim_advance_reservation(session, tenant_id, emp)
        pending_by_emp[emp_id] = pending
        _t, _u, outstanding = activity.get(
            emp_id, (Decimal("0"), Decimal("0"), Decimal("0"))
        )
        available = outstanding - pending
        if available < 0:
            available = Decimal("0")
        available_by_emp[emp_id] = available

    movements: list[dict[str, Any]] = []
    for je in journal_rows:
        emp = code_to_emp.get(str(je.account_code))
        if emp is None:
            continue
        debit = Decimal(str(je.debit or 0))
        credit = Decimal(str(je.credit or 0))
        if debit <= 0 and credit <= 0:
            continue
        inv = invoices.get(int(je.invoice_id)) if je.invoice_id else None
        doc_date = je.date
        if inv is not None and inv.invoice_date is not None:
            doc_date = inv.invoice_date
        if debit > 0:
            movement_type = "Advance"
            took = debit
            used = Decimal("0")
            cash = Decimal("0")
        else:
            movement_type = "Claim"
            took = Decimal("0")
            used = credit
            cash = cash_by_invoice.get(int(je.invoice_id), Decimal("0")) if je.invoice_id else Decimal("0")

        doc_no = ""
        doc_status = ""
        if inv is not None:
            doc_no = display_document_ref(inv)
            if not (doc_no or "").strip():
                doc_no = (inv.invoice_no or "").strip() or f"INV-{inv.id}"
            doc_status = _status_value(inv.status)
            # Prefer kind labels when helpful
            kind = (inv.team_expense_kind or "").strip().lower()
            if movement_type == "Advance" and kind and kind != TEAM_EXPENSE_KIND_ADVANCE:
                pass
            if movement_type == "Claim" and kind == TEAM_EXPENSE_KIND_ADVANCE:
                # Credit on advance ledger from a non-claim should still show as Used
                movement_type = "Claim"

        approved_by, approved_on = _approval_from_logs(
            approval_logs.get(int(je.invoice_id), []) if je.invoice_id else []
        )
        movements.append(
            {
                "emp": emp,
                "movement_type": movement_type,
                "document_no": doc_no,
                "document_date": doc_date,
                "took": took,
                "used": used,
                "cash_reimbursed": cash,
                "document_status": doc_status,
                "approved_by": approved_by,
                "approved_on": approved_on,
                "invoice_id": int(je.invoice_id or 0),
                "sort_date": doc_date or date.min,
                "sort_id": int(je.id),
            }
        )

    movements.sort(
        key=lambda m: (
            (m["emp"].name or "").lower(),
            (m["emp"].id or "").lower(),
            m["sort_date"],
            m["sort_id"],
        )
    )

    rows: list[EmployeeAdvanceDetailRow] = []
    running: dict[str, Decimal] = {}
    for m in movements:
        emp = m["emp"]
        emp_id = (emp.id or "").strip()
        balance = running.get(emp_id, Decimal("0"))
        balance = balance + m["took"] - m["used"]
        if balance < 0:
            balance = Decimal("0")
        running[emp_id] = balance
        pending = pending_by_emp.get(emp_id, Decimal("0"))
        available = available_by_emp.get(emp_id, Decimal("0"))
        rows.append(
            EmployeeAdvanceDetailRow(
                **_master_fields(emp),
                movement_type=m["movement_type"],
                document_no=m["document_no"],
                document_date=m["document_date"],
                took=m["took"],
                used=m["used"],
                outstanding_after=balance,
                pending_claims=pending,
                available=available,
                cash_reimbursed=m["cash_reimbursed"],
                document_status=m["document_status"],
                approved_by=m["approved_by"],
                approved_on=m["approved_on"],
                invoice_id=m["invoice_id"],
            )
        )
    return rows
