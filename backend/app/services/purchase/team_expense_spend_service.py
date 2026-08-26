"""Compute Team Expense period / category spend from processed invoices."""

from __future__ import annotations

import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    normalize_team_expense_kind,
)
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_APPROVAL, ROUTE_TEAM

_SPEND_KINDS = frozenset({TEAM_EXPENSE_KIND_CLAIM})
_COMMITTED_EXCLUDED_STATUSES = (
    InvoiceStatus.PROCESSED,
    InvoiceStatus.REJECTED,
    InvoiceStatus.DUPLICATE_SKIPPED,
)


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
    """YTD cumulative spend for a category ledger (expense claims only)."""
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


def period_key_bounds(period_kind: str, period_key: str) -> tuple[date, date] | None:
    """Parse a budget period key into inclusive date bounds."""
    kind = (period_kind or "").strip().lower()
    key = (period_key or "").strip()
    try:
        if kind == "monthly" and len(key) >= 7:
            y, m = int(key[:4]), int(key[5:7])
            return date(y, m, 1), date(y, m, monthrange(y, m)[1])
        if kind == "quarterly" and "-Q" in key.upper():
            y = int(key[:4])
            q = int(key.upper().split("-Q", 1)[1][:1])
            start_m = (q - 1) * 3 + 1
            end_m = start_m + 2
            return date(y, start_m, 1), date(y, end_m, monthrange(y, end_m)[1])
        if kind == "annual" and len(key) >= 4:
            y = int(key[:4])
            return date(y, 1, 1), date(y, 12, 31)
    except (TypeError, ValueError):
        return None
    return None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


SpendRow = tuple[str, str, float, date]


async def load_processed_claim_spend_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    date_from: date,
    date_to: date,
) -> list[SpendRow]:
    """One scan of processed TE claims in [date_from, date_to] for budget roll-ups."""
    effective = _effective_date_expr()
    rows = (
        await session.execute(
            select(
                Invoice.account_name,
                Invoice.account_code,
                Invoice.total,
                effective,
            ).where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_TEAM,
                Invoice.status == InvoiceStatus.PROCESSED,
                Invoice.team_expense_kind.in_(list(_SPEND_KINDS)),
                effective >= date_from,
                effective <= date_to,
            )
        )
    ).all()
    out: list[SpendRow] = []
    for name, code, total, effective_raw in rows:
        day = _as_date(effective_raw)
        if day is None:
            continue
        out.append(
            (
                (name or "").strip().lower(),
                (code or "").strip().lower(),
                float(total or 0),
                day,
            )
        )
    return out


async def load_committed_claim_spend_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    date_from: date,
    date_to: date,
) -> list[SpendRow]:
    """Approved-but-not-posted TE claims in [date_from, date_to]."""
    effective = _effective_date_expr()
    rows = (
        await session.execute(
            select(
                Invoice.account_name,
                Invoice.account_code,
                Invoice.total,
                effective,
            ).where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_TEAM,
                Invoice.status.notin_(_COMMITTED_EXCLUDED_STATUSES),
                func.coalesce(Invoice.evaluation_status, "") != EVAL_PENDING_APPROVAL,
                Invoice.team_expense_kind.in_(list(_SPEND_KINDS)),
                effective >= date_from,
                effective <= date_to,
            )
        )
    ).all()
    out: list[SpendRow] = []
    for name, code, total, effective_raw in rows:
        day = _as_date(effective_raw)
        if day is None:
            continue
        out.append(
            (
                (name or "").strip().lower(),
                (code or "").strip().lower(),
                float(total or 0),
                day,
            )
        )
    return out


def spend_for_tokens(
    rows: list[SpendRow],
    tokens: set[str],
    *,
    date_from: date,
    date_to: date,
) -> float:
    if not tokens:
        return 0.0
    wanted = {token.strip().lower() for token in tokens if token.strip()}
    total = 0.0
    for name, code, amount, day in rows:
        if day < date_from or day > date_to:
            continue
        if name in wanted or code in wanted:
            total += amount
    return total


async def gl_period_consumed(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    gl_ledger: str,
    period_kind: str,
    period_key: str,
    exclude_invoice_id: int | None = None,
    as_of: date | None = None,  # noqa: ARG001 — reserved for callers
    chart_of_accounts: list | None = None,
    include_children: bool = True,
) -> float:
    """Sum processed TE spend for a GL wallet over a budget period.

    When ``include_children`` is True and COA entries are provided (or loaded),
    spend posted to the parent **or any of its sub-ledgers** counts against the
    parent budget pot.
    """
    ledger = (gl_ledger or "").strip()
    if not ledger:
        return 0.0
    bounds = period_key_bounds(period_kind, period_key)
    if bounds is None:
        return 0.0
    date_from, date_to = bounds

    tokens = [ledger.lower()]
    if include_children:
        entries = list(chart_of_accounts or [])
        if not entries:
            from app.services.invoice.invoice_evaluation_service import load_config_for_tenant

            config = await load_config_for_tenant(session, tenant_id)
            entries = list(config.chart_of_accounts or [])
        from app.services.master_data.chart_of_accounts_service import child_ledger_names

        tokens = [t.lower() for t in child_ledger_names(ledger, entries)] or [ledger.lower()]

    effective = _effective_date_expr()
    stmt = select(func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.route_target == ROUTE_TEAM,
        Invoice.status == InvoiceStatus.PROCESSED,
        Invoice.team_expense_kind.in_(list(_SPEND_KINDS)),
        effective >= date_from,
        effective <= date_to,
        or_(
            func.lower(func.coalesce(Invoice.account_name, "")).in_(tokens),
            func.lower(func.coalesce(Invoice.account_code, "")).in_(tokens),
        ),
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    total = (await session.execute(stmt)).scalar_one()
    return float(Decimal(str(total or 0)))


async def gl_period_sub_breakdown(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    parent_gl: str,
    period_kind: str,
    period_key: str,
    chart_of_accounts: list | None = None,
    parent_budget: float = 0,
    spend_rows: list[SpendRow] | None = None,
) -> list[dict[str, float | str]]:
    """Per-child spend under a parent wallet for the period (track-only labels)."""
    from app.services.master_data.chart_of_accounts_service import (
        sub_ledgers_for_ledger,
    )

    parent = (parent_gl or "").strip()
    if not parent:
        return []
    entries = list(chart_of_accounts or [])
    if not entries:
        from app.services.invoice.invoice_evaluation_service import load_config_for_tenant

        config = await load_config_for_tenant(session, tenant_id)
        entries = list(config.chart_of_accounts or [])

    children = sub_ledgers_for_ledger(parent, entries)
    # Include direct posts to the parent itself as a "Parent" row when present.
    labels: list[tuple[str, str]] = [(parent, parent)]
    for sub in children:
        name = (sub.name or "").strip()
        if name:
            labels.append((name, name))

    bounds = period_key_bounds(period_kind, period_key)
    rows: list[dict[str, float | str]] = []
    budget = float(parent_budget or 0)
    loaded_rows = spend_rows
    if loaded_rows is None and bounds is not None:
        loaded_rows = await load_processed_claim_spend_rows(
            session,
            tenant_id,
            date_from=bounds[0],
            date_to=bounds[1],
        )
    for label, token in labels:
        if loaded_rows is not None and bounds is not None:
            spent = spend_for_tokens(
                loaded_rows,
                {token},
                date_from=bounds[0],
                date_to=bounds[1],
            )
        else:
            spent = await gl_period_consumed(
                session,
                tenant_id,
                gl_ledger=token,
                period_kind=period_kind,
                period_key=period_key,
                chart_of_accounts=entries,
                include_children=False,
            )
        pct = round((spent / budget) * 100.0, 2) if budget > 0 else None
        rows.append(
            {
                "gl_ledger": label,
                "consumed": spent,
                "pct_of_budget": pct if pct is not None else 0.0,
            }
        )
    # Drop zero parent row when children exist and parent itself has no direct spend.
    if children and rows and rows[0]["gl_ledger"] == parent and float(rows[0]["consumed"]) == 0:
        rows = rows[1:]
    return rows


async def department_period_consumed(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    department: str = "",
    period_kind: str,
    period_key: str,
    gl_ledger: str | None = None,
    employee_emails: list[str] | None = None,  # noqa: ARG001 — legacy unused
    exclude_invoice_id: int | None = None,
    as_of: date | None = None,
) -> float:
    """Compatibility wrapper — spend is tracked by GL account, not department."""
    return await gl_period_consumed(
        session,
        tenant_id,
        gl_ledger=gl_ledger or "",
        period_kind=period_kind,
        period_key=period_key,
        exclude_invoice_id=exclude_invoice_id,
        as_of=as_of,
    )


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
