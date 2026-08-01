"""Employee advance balances read from the Staff Advance sub-ledger journal lines."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
    RuleBookConfigPayload,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
from app.services.master_data.party_coa_subledger_service import (
    employee_advance_parent_ledger,
    party_sub_ledger_code,
    resolve_party_child_mapping,
)


_PENDING_EXCLUDED_STATUSES = (
    InvoiceStatus.PROCESSED,
    InvoiceStatus.REJECTED,
    InvoiceStatus.DUPLICATE_SKIPPED,
)


def employee_advance_account_code(
    config: RuleBookConfigPayload,
    *,
    employee_id: str,
    employee_parent_ledger: str | None = None,
) -> str:
    """Account code of the employee advance child, empty when it does not exist yet."""
    parent = employee_advance_parent_ledger(
        config,
        employee_parent_ledger=employee_parent_ledger,
    )
    if not parent or not (employee_id or "").strip():
        return ""
    child = resolve_party_child_mapping(
        config,
        parent_ledger_name=parent,
        slug=employee_id,
    )
    if child is not None:
        return child.account_code
    return party_sub_ledger_code(employee_id)


async def employee_advance_balance(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: RuleBookConfigPayload,
    *,
    employee_id: str,
    employee_parent_ledger: str | None = None,
) -> Decimal:
    """Outstanding advance held by the employee (debits less credits, never negative)."""
    code = employee_advance_account_code(
        config,
        employee_id=employee_id,
        employee_parent_ledger=employee_parent_ledger,
    )
    if not code:
        return Decimal("0")

    total = (
        await session.execute(
            select(
                func.coalesce(func.sum(JournalEntry.debit), 0)
                - func.coalesce(func.sum(JournalEntry.credit), 0)
            ).where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.account_code == code,
            )
        )
    ).scalar_one()
    balance = Decimal(str(total or 0))
    return balance if balance > 0 else Decimal("0")


async def employee_advance_balances_by_ids(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: RuleBookConfigPayload,
    employees: Sequence[Any],
) -> dict[str, Decimal]:
    """Batch outstanding advance per employee id (0 when no child / no journals)."""
    code_by_employee: dict[str, str] = {}
    for employee in employees:
        emp_id = str(getattr(employee, "id", "") or "").strip()
        if not emp_id:
            continue
        parent = getattr(employee, "advance_parent_ledger", "") or ""
        code = employee_advance_account_code(
            config,
            employee_id=emp_id,
            employee_parent_ledger=parent,
        )
        if code:
            code_by_employee[emp_id] = code

    balances: dict[str, Decimal] = {
        str(getattr(employee, "id", "") or "").strip(): Decimal("0")
        for employee in employees
        if str(getattr(employee, "id", "") or "").strip()
    }
    if not code_by_employee:
        return balances

    codes = list(set(code_by_employee.values()))
    rows = (
        await session.execute(
            select(
                JournalEntry.account_code,
                func.coalesce(func.sum(JournalEntry.debit), 0)
                - func.coalesce(func.sum(JournalEntry.credit), 0),
            )
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.account_code.in_(codes),
            )
            .group_by(JournalEntry.account_code)
        )
    ).all()
    net_by_code = {
        str(code): (Decimal(str(net or 0)) if Decimal(str(net or 0)) > 0 else Decimal("0"))
        for code, net in rows
    }
    for emp_id, code in code_by_employee.items():
        balances[emp_id] = net_by_code.get(code, Decimal("0"))
    return balances


async def pending_against_advance_total(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    employee: Any,
    *,
    exclude_invoice_id: int | None = None,
) -> Decimal:
    """Sum of open against-advance TE claims for this employee (excludes terminal statuses)."""
    from app.services.purchase.team_expense_validator import find_employee_by_sender

    stmt = select(Invoice.id, Invoice.total, Invoice.email_sender).where(
        Invoice.tenant_id == tenant_id,
        Invoice.route_target == ROUTE_TEAM,
        Invoice.team_expense_kind == TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
        Invoice.status.notin_(_PENDING_EXCLUDED_STATUSES),
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)

    total = Decimal("0")
    for _inv_id, amount, sender in (await session.execute(stmt)).all():
        if find_employee_by_sender([employee], sender) is None:
            continue
        if amount is None:
            continue
        total += Decimal(str(amount))
    return total if total > 0 else Decimal("0")


async def employee_available_advance(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: RuleBookConfigPayload,
    employee: Any,
    *,
    exclude_invoice_id: int | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (available, ledger_balance, pending_others) for against-advance gating."""
    emp_id = str(getattr(employee, "id", "") or "").strip()
    ledger = await employee_advance_balance(
        session,
        tenant_id,
        config,
        employee_id=emp_id,
        employee_parent_ledger=getattr(employee, "advance_parent_ledger", "") or "",
    )
    pending = await pending_against_advance_total(
        session,
        tenant_id,
        employee,
        exclude_invoice_id=exclude_invoice_id,
    )
    available = ledger - pending
    if available < 0:
        available = Decimal("0")
    return available, ledger, pending
