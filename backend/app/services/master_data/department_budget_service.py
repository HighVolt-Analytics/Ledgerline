"""CRUD and utilization for department budget envelopes."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department_budget import DepartmentBudget
from app.schemas.department_budget import (
    DepartmentBudgetCreate,
    DepartmentBudgetResponse,
    DepartmentBudgetUpdate,
    DepartmentBudgetUtilizationRow,
)
from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
from app.services.master_data.master_data_service import list_employee_masters
from app.services.purchase.team_expense_advance_service import (
    employee_advance_balances_by_ids,
)
from app.services.purchase.team_expense_spend_service import (
    current_period_keys,
    department_period_consumed,
)


def _tenant_id(tenant_id: uuid.UUID | int | str) -> uuid.UUID:
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    return uuid.UUID(str(tenant_id))


def _to_response(row: DepartmentBudget) -> DepartmentBudgetResponse:
    return DepartmentBudgetResponse(
        id=row.id,
        department=row.department or "",
        gl_ledger=row.gl_ledger or "",
        period_kind=row.period_kind,  # type: ignore[arg-type]
        period_key=row.period_key,
        allocated=Decimal(str(row.allocated or 0)),
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_department_budgets(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    department: str | None = None,
) -> list[DepartmentBudgetResponse]:
    tid = _tenant_id(tenant_id)
    stmt = (
        select(DepartmentBudget)
        .where(DepartmentBudget.tenant_id == tid)
        .order_by(
            DepartmentBudget.department,
            DepartmentBudget.period_kind,
            DepartmentBudget.period_key.desc(),
            DepartmentBudget.gl_ledger,
        )
    )
    if department and department.strip():
        stmt = stmt.where(DepartmentBudget.department == department.strip())
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_response(row) for row in rows]


async def create_department_budget(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    body: DepartmentBudgetCreate,
) -> DepartmentBudgetResponse:
    tid = _tenant_id(tenant_id)
    gl = body.gl_ledger or ""
    existing = (
        await session.execute(
            select(DepartmentBudget.id).where(
                DepartmentBudget.tenant_id == tid,
                DepartmentBudget.department == body.department,
                DepartmentBudget.gl_ledger == gl,
                DepartmentBudget.period_kind == body.period_kind,
                DepartmentBudget.period_key == body.period_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            "A department budget already exists for this department, GL, and period"
        )
    row = DepartmentBudget(
        tenant_id=tid,
        department=body.department,
        gl_ledger=gl,
        period_kind=body.period_kind,
        period_key=body.period_key,
        allocated=body.allocated,
        notes=body.notes,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _to_response(row)


async def update_department_budget(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    budget_id: int,
    body: DepartmentBudgetUpdate,
) -> DepartmentBudgetResponse:
    tid = _tenant_id(tenant_id)
    row = (
        await session.execute(
            select(DepartmentBudget).where(
                DepartmentBudget.tenant_id == tid,
                DepartmentBudget.id == budget_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"Department budget {budget_id} not found")
    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if key == "gl_ledger" and value is None:
            value = ""
        setattr(row, key, value)
    conflict = (
        await session.execute(
            select(DepartmentBudget.id).where(
                DepartmentBudget.tenant_id == tid,
                DepartmentBudget.department == row.department,
                DepartmentBudget.gl_ledger == (row.gl_ledger or ""),
                DepartmentBudget.period_kind == row.period_kind,
                DepartmentBudget.period_key == row.period_key,
                DepartmentBudget.id != budget_id,
            )
        )
    ).scalar_one_or_none()
    if conflict is not None:
        raise ValueError(
            "A department budget already exists for this department, GL, and period"
        )
    await session.flush()
    await session.refresh(row)
    return _to_response(row)


async def delete_department_budget(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    budget_id: int,
) -> None:
    tid = _tenant_id(tenant_id)
    row = (
        await session.execute(
            select(DepartmentBudget).where(
                DepartmentBudget.tenant_id == tid,
                DepartmentBudget.id == budget_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"Department budget {budget_id} not found")
    await session.delete(row)
    await session.flush()


def _remaining(cap: float, spent: float) -> float | None:
    if cap is None or float(cap) <= 0:
        return None
    return max(0.0, float(cap) - float(spent or 0))


def _utilization_pct(cap: float, spent: float) -> float | None:
    if cap is None or float(cap) <= 0:
        return None
    return round((float(spent or 0) / float(cap)) * 100.0, 2)


async def _department_advance_float_map(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, float]:
    """Sum outstanding Staff Advance balances keyed by employee department name."""
    config = await load_config_for_tenant(session, tenant_id)
    employees = await list_employee_masters(
        session, tenant_id, include_advance_balances=False
    )
    balances = await employee_advance_balances_by_ids(
        session, tenant_id, config, employees
    )
    by_dept: dict[str, float] = defaultdict(float)
    for emp in employees:
        dept = (emp.department or "").strip()
        if not dept:
            continue
        emp_id = (emp.id or "").strip()
        float_amt = float(balances.get(emp_id, Decimal("0")) or 0)
        if float_amt > 0:
            by_dept[dept] += float_amt
    return dict(by_dept)


async def build_department_budget_utilization_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    as_of: date | None = None,
    current_period_only: bool = True,
) -> list[DepartmentBudgetUtilizationRow]:
    """Department envelope allocated vs consumed from processed TE invoices.

    Accrual ``consumed`` / ``remaining`` exclude advances. Cash columns reserve
    outstanding department advance float against dept-wide (empty GL) envelopes
    so managers see cash still available after float held by employees.
    """
    tid = _tenant_id(tenant_id)
    today = as_of or date.today()
    keys = current_period_keys(today)
    budgets = await list_department_budgets(session, tid)
    advance_by_dept = await _department_advance_float_map(session, tid)
    rows: list[DepartmentBudgetUtilizationRow] = []
    for bud in budgets:
        if current_period_only and keys.get(bud.period_kind) != bud.period_key:
            continue
        consumed = await department_period_consumed(
            session,
            tid,
            department=bud.department,
            period_kind=bud.period_kind,
            period_key=bud.period_key,
            gl_ledger=bud.gl_ledger or None,
            as_of=today,
        )
        allocated = float(bud.allocated or 0)
        consumed_f = float(consumed)
        advance_float = float(advance_by_dept.get((bud.department or "").strip(), 0) or 0)
        # Reserve float only on dept-wide envelopes to avoid charging every GL slice.
        gl = (bud.gl_ledger or "").strip()
        cash_committed = consumed_f + advance_float if not gl else consumed_f
        rows.append(
            DepartmentBudgetUtilizationRow(
                department=bud.department,
                gl_ledger=bud.gl_ledger or "",
                period_kind=bud.period_kind,
                period_key=bud.period_key,
                allocated=allocated,
                consumed=consumed_f,
                remaining=_remaining(allocated, consumed_f),
                utilization_pct=_utilization_pct(allocated, consumed_f),
                notes=bud.notes,
                budget_id=bud.id,
                advance_float=advance_float,
                cash_committed=cash_committed,
                cash_remaining=_remaining(allocated, cash_committed),
                cash_utilization_pct=_utilization_pct(allocated, cash_committed),
            )
        )
    return rows
