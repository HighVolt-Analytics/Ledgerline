"""Compute Team Expense period / category spend from processed invoices."""

from __future__ import annotations

import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    normalize_team_expense_kind,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM

_SPEND_KINDS = frozenset({TEAM_EXPENSE_KIND_CLAIM, TEAM_EXPENSE_KIND_AGAINST_ADVANCE})


def normalize_employee_email(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if "<" in raw and ">" in raw:
        inner = raw.rsplit("<", 1)[-1].split(">", 1)[0].strip()
        if "@" in inner:
            return inner
    return raw


@dataclass(frozen=True)
class PeriodSpend:
    mtd: float
    qtd: float
    ytd: float


def period_bounds(as_of: date) -> tuple[date, date, date, date, date, date]:
    """Return (month_start, month_end, quarter_start, quarter_end, year_start, year_end)."""
    month_start = date(as_of.year, as_of.month, 1)
    month_end = date(as_of.year, as_of.month, monthrange(as_of.year, as_of.month)[1])
    q = (as_of.month - 1) // 3
    quarter_start = date(as_of.year, q * 3 + 1, 1)
    q_end_month = q * 3 + 3
    quarter_end = date(as_of.year, q_end_month, monthrange(as_of.year, q_end_month)[1])
    year_start = date(as_of.year, 1, 1)
    year_end = date(as_of.year, 12, 31)
    return month_start, month_end, quarter_start, quarter_end, year_start, year_end


def current_period_keys(as_of: date) -> dict[str, str]:
    q = (as_of.month - 1) // 3 + 1
    return {
        "monthly": f"{as_of.year:04d}-{as_of.month:02d}",
        "quarterly": f"{as_of.year:04d}-Q{q}",
        "annual": f"{as_of.year:04d}",
    }


def _effective_date_expr():
    return func.coalesce(Invoice.invoice_date, func.date(Invoice.created_at))


async def _sum_processed_spend(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    employee_email: str,
    date_from: date | None = None,
    date_to: date | None = None,
    ledger: str | None = None,
    exclude_invoice_id: int | None = None,
) -> float:
    email = normalize_employee_email(employee_email)
    if not email:
        return 0.0

    effective = _effective_date_expr()
    stmt = select(func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.route_target == ROUTE_TEAM,
        Invoice.status == InvoiceStatus.PROCESSED,
        Invoice.team_expense_kind.in_(list(_SPEND_KINDS)),
        func.lower(func.trim(Invoice.employee_email)) == email,
    )
    if date_from is not None:
        stmt = stmt.where(effective >= date_from)
    if date_to is not None:
        stmt = stmt.where(effective <= date_to)
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    if ledger:
        token = ledger.strip().lower()
        stmt = stmt.where(
            or_(
                func.lower(func.coalesce(Invoice.account_name, "")) == token,
                func.lower(func.coalesce(Invoice.account_code, "")) == token,
            )
        )

    total = (await session.execute(stmt)).scalar_one()
    return float(Decimal(str(total or 0)))


async def employee_period_spend(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    employee_email: str,
    *,
    as_of: date | None = None,
    exclude_invoice_id: int | None = None,
) -> PeriodSpend:
    today = as_of or date.today()
    m_start, m_end, q_start, q_end, y_start, y_end = period_bounds(today)
    mtd = await _sum_processed_spend(
        session,
        tenant_id,
        employee_email=employee_email,
        date_from=m_start,
        date_to=min(m_end, today),
        exclude_invoice_id=exclude_invoice_id,
    )
    qtd = await _sum_processed_spend(
        session,
        tenant_id,
        employee_email=employee_email,
        date_from=q_start,
        date_to=min(q_end, today),
        exclude_invoice_id=exclude_invoice_id,
    )
    ytd = await _sum_processed_spend(
        session,
        tenant_id,
        employee_email=employee_email,
        date_from=y_start,
        date_to=min(y_end, today),
        exclude_invoice_id=exclude_invoice_id,
    )
    return PeriodSpend(mtd=mtd, qtd=qtd, ytd=ytd)


async def employee_category_spend(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    employee_email: str,
    ledger: str,
    *,
    as_of: date | None = None,
    exclude_invoice_id: int | None = None,
) -> float:
    """YTD cumulative spend for a category ledger (expense claim / against-advance)."""
    today = as_of or date.today()
    bounds = period_bounds(today)
    y_start, y_end = bounds[4], bounds[5]
    return await _sum_processed_spend(
        session,
        tenant_id,
        employee_email=employee_email,
        date_from=y_start,
        date_to=min(y_end, today),
        ledger=ledger,
        exclude_invoice_id=exclude_invoice_id,
    )


async def department_period_consumed(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    department: str,
    period_kind: str,
    period_key: str,
    gl_ledger: str | None = None,
    employee_emails: list[str] | None = None,
    exclude_invoice_id: int | None = None,
    as_of: date | None = None,  # noqa: ARG001 — reserved for callers
) -> float:
    """Sum processed TE spend for employees in a department for a budget period."""
    emails = [normalize_employee_email(e) for e in (employee_emails or []) if normalize_employee_email(e)]
    if not emails:
        from app.models.employee_master import EmployeeMasterRecord

        dept_key = (department or "").strip().casefold()
        if not dept_key:
            return 0.0
        all_emps = (
            await session.execute(
                select(EmployeeMasterRecord.email, EmployeeMasterRecord.department).where(
                    EmployeeMasterRecord.tenant_id == tenant_id
                )
            )
        ).all()
        emails = [
            normalize_employee_email(email)
            for email, dept in all_emps
            if (dept or "").strip().casefold() == dept_key and normalize_employee_email(email)
        ]
    if not emails:
        return 0.0

    kind = (period_kind or "").strip().lower()
    key = (period_key or "").strip()
    date_from: date | None = None
    date_to: date | None = None
    try:
        if kind == "monthly" and len(key) >= 7:
            y, m = int(key[:4]), int(key[5:7])
            date_from = date(y, m, 1)
            date_to = date(y, m, monthrange(y, m)[1])
        elif kind == "quarterly" and "-Q" in key.upper():
            y = int(key[:4])
            q = int(key.upper().split("-Q", 1)[1][:1])
            start_m = (q - 1) * 3 + 1
            end_m = start_m + 2
            date_from = date(y, start_m, 1)
            date_to = date(y, end_m, monthrange(y, end_m)[1])
        elif kind == "annual" and len(key) >= 4:
            y = int(key[:4])
            date_from = date(y, 1, 1)
            date_to = date(y, 12, 31)
    except (TypeError, ValueError):
        return 0.0
    if date_from is None or date_to is None:
        return 0.0

    effective = _effective_date_expr()
    stmt = select(func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.route_target == ROUTE_TEAM,
        Invoice.status == InvoiceStatus.PROCESSED,
        Invoice.team_expense_kind.in_(list(_SPEND_KINDS)),
        func.lower(func.trim(Invoice.employee_email)).in_(emails),
        effective >= date_from,
        effective <= date_to,
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    ledger = (gl_ledger or "").strip()
    if ledger:
        token = ledger.lower()
        stmt = stmt.where(
            or_(
                func.lower(func.coalesce(Invoice.account_name, "")) == token,
                func.lower(func.coalesce(Invoice.account_code, "")) == token,
            )
        )
    total = (await session.execute(stmt)).scalar_one()
    return float(Decimal(str(total or 0)))


def counts_toward_spend(team_expense_kind: str | None) -> bool:
    kind = normalize_team_expense_kind(team_expense_kind)
    return kind != TEAM_EXPENSE_KIND_ADVANCE and kind in _SPEND_KINDS


async def rebuild_employee_spend_cache(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    employee_row: Any,
    *,
    as_of: date | None = None,
) -> PeriodSpend:
    """Refresh mtd/qtd/ytd cache columns from invoice truth."""
    email = normalize_employee_email(getattr(employee_row, "email", None))
    spend = await employee_period_spend(session, tenant_id, email, as_of=as_of)
    employee_row.mtd_spent = spend.mtd
    employee_row.qtd_spent = spend.qtd
    employee_row.ytd_spent = spend.ytd
    return spend
