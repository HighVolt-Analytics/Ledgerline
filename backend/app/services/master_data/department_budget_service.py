"""CRUD and utilization for GL-account budget envelopes."""

from __future__ import annotations

import uuid
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
    GlBudgetSubBreakdownRow,
    ParentGlBudgetTreeUpsert,
)
from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
from app.services.purchase.team_expense_spend_service import (
    current_period_keys,
    gl_period_consumed,
    gl_period_sub_breakdown,
)


def _tenant_id(tenant_id: uuid.UUID | int | str) -> uuid.UUID:
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    return uuid.UUID(str(tenant_id))


def _to_response(row: DepartmentBudget) -> DepartmentBudgetResponse:
    enforcement = (getattr(row, "enforcement", None) or "soft").strip().lower()
    if enforcement not in {"soft", "hard"}:
        enforcement = "soft"
    return DepartmentBudgetResponse(
        id=row.id,
        department=row.department or "",
        gl_ledger=row.gl_ledger or "",
        period_kind=row.period_kind,  # type: ignore[arg-type]
        period_key=row.period_key,
        allocated=Decimal(str(row.allocated or 0)),
        enforcement=enforcement,  # type: ignore[arg-type]
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_department_budgets(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    department: str | None = None,
    gl_ledger: str | None = None,
) -> list[DepartmentBudgetResponse]:
    tid = _tenant_id(tenant_id)
    stmt = (
        select(DepartmentBudget)
        .where(DepartmentBudget.tenant_id == tid)
        .order_by(
            DepartmentBudget.gl_ledger,
            DepartmentBudget.period_kind,
            DepartmentBudget.period_key.desc(),
        )
    )
    if department and department.strip():
        stmt = stmt.where(DepartmentBudget.department == department.strip())
    if gl_ledger and gl_ledger.strip():
        stmt = stmt.where(DepartmentBudget.gl_ledger == gl_ledger.strip())
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_response(row) for row in rows]


async def create_department_budget(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    body: DepartmentBudgetCreate,
) -> DepartmentBudgetResponse:
    tid = _tenant_id(tenant_id)
    gl = (body.gl_ledger or "").strip()
    if not gl:
        raise ValueError("GL account is required")
    existing = (
        await session.execute(
            select(DepartmentBudget.id).where(
                DepartmentBudget.tenant_id == tid,
                DepartmentBudget.gl_ledger == gl,
                DepartmentBudget.period_kind == body.period_kind,
                DepartmentBudget.period_key == body.period_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            "A budget already exists for this GL account and period"
        )
    row = DepartmentBudget(
        tenant_id=tid,
        department=(body.department or "").strip(),
        gl_ledger=gl,
        period_kind=body.period_kind,
        period_key=body.period_key,
        allocated=body.allocated,
        enforcement=body.enforcement or "soft",
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
        raise LookupError(f"GL account budget {budget_id} not found")
    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if key == "department" and value is None:
            value = ""
        setattr(row, key, value)
    if not (row.gl_ledger or "").strip():
        raise ValueError("GL account is required")
    conflict = (
        await session.execute(
            select(DepartmentBudget.id).where(
                DepartmentBudget.tenant_id == tid,
                DepartmentBudget.gl_ledger == (row.gl_ledger or "").strip(),
                DepartmentBudget.period_kind == row.period_kind,
                DepartmentBudget.period_key == row.period_key,
                DepartmentBudget.id != budget_id,
            )
        )
    ).scalar_one_or_none()
    if conflict is not None:
        raise ValueError(
            "A budget already exists for this GL account and period"
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
        raise LookupError(f"GL account budget {budget_id} not found")
    await session.delete(row)
    await session.flush()


async def _upsert_gl_budget_row(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    gl_ledger: str,
    period_kind: str,
    period_key: str,
    allocated: Decimal,
    notes: str | None = None,
    enforcement: str = "soft",
) -> DepartmentBudget:
    gl = (gl_ledger or "").strip()
    mode = (enforcement or "soft").strip().lower()
    if mode not in {"soft", "hard"}:
        mode = "soft"
    row = (
        await session.execute(
            select(DepartmentBudget).where(
                DepartmentBudget.tenant_id == tenant_id,
                DepartmentBudget.gl_ledger == gl,
                DepartmentBudget.period_kind == period_kind,
                DepartmentBudget.period_key == period_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DepartmentBudget(
            tenant_id=tenant_id,
            department="",
            gl_ledger=gl,
            period_kind=period_kind,
            period_key=period_key,
            allocated=allocated,
            enforcement=mode,
            notes=notes,
        )
        session.add(row)
    else:
        row.allocated = allocated
        row.enforcement = mode
        if notes is not None:
            row.notes = notes
    await session.flush()
    await session.refresh(row)
    return row


async def upsert_parent_gl_budget_tree(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    body: ParentGlBudgetTreeUpsert,
) -> list[DepartmentBudgetResponse]:
    """Save parent wallet + every Sub-GL allocation for a period.

    When the parent has COA children, every child must be listed and
    ``sum(sub_allocations)`` must equal the parent ``allocated``.
    """
    from app.services.master_data.chart_of_accounts_service import (
        _find_coa_entry,
        sub_ledgers_for_ledger,
    )

    tid = _tenant_id(tenant_id)
    parent = (body.parent_gl or "").strip()
    if not parent:
        raise ValueError("Parent GL is required")

    config = await load_config_for_tenant(session, tid)
    coa = list(config.chart_of_accounts or [])
    entry = _find_coa_entry(parent, coa)
    if entry is None:
        raise ValueError(f"Parent GL {parent!r} is not in your chart of accounts")
    parent_name = (entry.name or "").strip() or parent
    catalog_subs = [sub.name.strip() for sub in sub_ledgers_for_ledger(parent_name, coa) if sub.name.strip()]

    parent_allocated = Decimal(str(body.allocated or 0))
    provided = {
        (item.gl_ledger or "").strip(): Decimal(str(item.allocated or 0))
        for item in body.sub_allocations
        if (item.gl_ledger or "").strip()
    }

    if catalog_subs:
        missing = [name for name in catalog_subs if name not in provided]
        if missing:
            raise ValueError(
                "Set a budget for every Sub-GL under this parent: "
                + ", ".join(missing)
            )
        extra = [name for name in provided if name not in set(catalog_subs)]
        if extra:
            raise ValueError(
                "Unknown Sub-GL for this parent: " + ", ".join(extra)
            )
        sub_total = sum(provided.values(), Decimal("0"))
        if sub_total != parent_allocated:
            raise ValueError(
                f"Sum of Sub-GL budgets ({sub_total}) must equal parent budget ({parent_allocated})"
            )
    elif provided:
        raise ValueError(
            f"Parent GL {parent_name!r} has no Sub-GLs in the chart of accounts"
        )

    saved: list[DepartmentBudget] = []
    parent_row = await _upsert_gl_budget_row(
        session,
        tid,
        gl_ledger=parent_name,
        period_kind=body.period_kind,
        period_key=body.period_key,
        allocated=parent_allocated,
        notes=body.notes,
        enforcement=body.enforcement or "soft",
    )
    saved.append(parent_row)

    for sub_name in catalog_subs:
        sub_row = await _upsert_gl_budget_row(
            session,
            tid,
            gl_ledger=sub_name,
            period_kind=body.period_kind,
            period_key=body.period_key,
            allocated=provided[sub_name],
            notes=None,
            enforcement=body.enforcement or "soft",
        )
        saved.append(sub_row)

    return [_to_response(row) for row in saved]


async def delete_parent_gl_budget_tree(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    parent_gl: str,
    period_kind: str,
    period_key: str,
) -> int:
    """Delete parent wallet and its COA Sub-GL budgets for one period."""
    from app.services.master_data.chart_of_accounts_service import (
        _find_coa_entry,
        sub_ledgers_for_ledger,
    )

    tid = _tenant_id(tenant_id)
    parent = (parent_gl or "").strip()
    if not parent:
        raise ValueError("Parent GL is required")
    config = await load_config_for_tenant(session, tid)
    coa = list(config.chart_of_accounts or [])
    entry = _find_coa_entry(parent, coa)
    parent_name = (entry.name or "").strip() if entry is not None else parent
    names = {parent_name}
    if entry is not None:
        for sub in sub_ledgers_for_ledger(parent_name, coa):
            if (sub.name or "").strip():
                names.add(sub.name.strip())

    rows = (
        await session.execute(
            select(DepartmentBudget).where(
                DepartmentBudget.tenant_id == tid,
                DepartmentBudget.period_kind == period_kind,
                DepartmentBudget.period_key == period_key,
                DepartmentBudget.gl_ledger.in_(sorted(names)),
            )
        )
    ).scalars().all()
    if not rows:
        raise LookupError("No GL budgets found for this parent and period")
    for row in rows:
        await session.delete(row)
    await session.flush()
    return len(rows)
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
        raise LookupError(f"GL account budget {budget_id} not found")
    await session.delete(row)
    await session.flush()


def _remaining(cap: float, spent: float) -> float | None:
    if cap is None or float(cap) <= 0:
        return None
    # Can be negative when overspent (shown as over budget).
    return float(cap) - float(spent or 0)


def _utilization_pct(cap: float, spent: float) -> float | None:
    if cap is None or float(cap) <= 0:
        return None
    return round((float(spent or 0) / float(cap)) * 100.0, 2)


async def build_department_budget_utilization_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    as_of: date | None = None,
    current_period_only: bool = True,
) -> list[DepartmentBudgetUtilizationRow]:
    """GL | Budget | Spent | Left — parent wallets roll up; Sub-GL wallets are exact."""
    from app.services.master_data.chart_of_accounts_service import account_is_sub_ledger

    tid = _tenant_id(tenant_id)
    today = as_of or date.today()
    keys = current_period_keys(today)
    budgets = await list_department_budgets(session, tid)
    config = await load_config_for_tenant(session, tid)
    coa = list(config.chart_of_accounts or [])
    rows: list[DepartmentBudgetUtilizationRow] = []
    for bud in budgets:
        if current_period_only and keys.get(bud.period_kind) != bud.period_key:
            continue
        gl = (bud.gl_ledger or "").strip()
        if not gl:
            continue
        is_sub = account_is_sub_ledger(gl, coa)
        consumed = await gl_period_consumed(
            session,
            tid,
            gl_ledger=gl,
            period_kind=bud.period_kind,
            period_key=bud.period_key,
            as_of=today,
            chart_of_accounts=coa,
            include_children=not is_sub,
        )
        allocated = float(bud.allocated or 0)
        consumed_f = float(consumed)
        breakdown: list[GlBudgetSubBreakdownRow] = []
        if not is_sub:
            raw_breakdown = await gl_period_sub_breakdown(
                session,
                tid,
                parent_gl=gl,
                period_kind=bud.period_kind,
                period_key=bud.period_key,
                chart_of_accounts=coa,
                parent_budget=allocated,
            )
            breakdown = [
                GlBudgetSubBreakdownRow(
                    gl_ledger=str(item["gl_ledger"]),
                    consumed=float(item["consumed"] or 0),
                    pct_of_budget=float(item.get("pct_of_budget") or 0),
                )
                for item in raw_breakdown
            ]
        rows.append(
            DepartmentBudgetUtilizationRow(
                gl_ledger=gl,
                period_kind=bud.period_kind,
                period_key=bud.period_key,
                allocated=allocated,
                consumed=consumed_f,
                remaining=_remaining(allocated, consumed_f),
                utilization_pct=_utilization_pct(allocated, consumed_f),
                department=bud.department or "",
                enforcement=(bud.enforcement or "soft"),  # type: ignore[arg-type]
                notes=bud.notes,
                budget_id=bud.id,
                sub_breakdown=breakdown,
            )
        )
    return rows
