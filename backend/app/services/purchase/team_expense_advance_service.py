"""Employee advance balances read from the Staff Advance sub-ledger journal lines."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_CLAIM,
    RuleBookConfigPayload,
    normalize_team_expense_kind,
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

# Open expense claims reserve float until posted (partial netting at settlement).
_LEGACY_AGAINST_ADVANCE = "expense_against_advance"


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
    """Net debit balance on the employee Staff Advance child (float outstanding)."""
    code = employee_advance_account_code(
        config,
        employee_id=employee_id,
        employee_parent_ledger=employee_parent_ledger,
    )
    if not code:
        return Decimal("0")
    net = (
        await session.execute(
            select(
                func.coalesce(func.sum(JournalEntry.debit - JournalEntry.credit), 0)
            ).where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.account_code == code,
            )
        )
    ).scalar_one()
    balance = Decimal(str(net or 0))
    return balance if balance > 0 else Decimal("0")


async def employee_advance_activity_by_ids(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: RuleBookConfigPayload,
    employees: Sequence[Any],
) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    """Batch (taken, used, outstanding) per employee from Staff Advance journals.

    Taken = sum of debits (advance requisitions paid out).
    Used = sum of credits (claims that netted the advance).
    Outstanding = max(taken − used, 0).
    """
    activity: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    code_by_employee: dict[str, str] = {}
    for emp in employees:
        emp_id = str(getattr(emp, "id", "") or "").strip()
        if not emp_id:
            continue
        code = employee_advance_account_code(
            config,
            employee_id=emp_id,
            employee_parent_ledger=getattr(emp, "advance_parent_ledger", "") or "",
        )
        if code:
            code_by_employee[emp_id] = code
        activity[emp_id] = (Decimal("0"), Decimal("0"), Decimal("0"))
    if not code_by_employee:
        return activity

    codes = list(set(code_by_employee.values()))
    rows = (
        await session.execute(
            select(
                JournalEntry.account_code,
                func.coalesce(func.sum(JournalEntry.debit), 0),
                func.coalesce(func.sum(JournalEntry.credit), 0),
            )
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.account_code.in_(codes),
            )
            .group_by(JournalEntry.account_code)
        )
    ).all()
    by_code: dict[str, tuple[Decimal, Decimal]] = {}
    for code, debits, credits in rows:
        taken = Decimal(str(debits or 0))
        used = Decimal(str(credits or 0))
        if taken < 0:
            taken = Decimal("0")
        if used < 0:
            used = Decimal("0")
        by_code[str(code)] = (taken, used)

    for emp_id, code in code_by_employee.items():
        taken, used = by_code.get(code, (Decimal("0"), Decimal("0")))
        outstanding = taken - used
        if outstanding < 0:
            outstanding = Decimal("0")
        activity[emp_id] = (taken, used, outstanding)
    return activity


async def employee_advance_balances_by_ids(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: RuleBookConfigPayload,
    employees: Sequence[Any],
) -> dict[str, Decimal]:
    """Batch Staff Advance balances keyed by employee master id."""
    activity = await employee_advance_activity_by_ids(
        session, tenant_id, config, employees
    )
    return {emp_id: outstanding for emp_id, (_t, _u, outstanding) in activity.items()}


def _is_claim_kind(raw_kind: str | None) -> bool:
    cleaned = (raw_kind or "").strip().lower()
    if cleaned == _LEGACY_AGAINST_ADVANCE:
        return True
    return normalize_team_expense_kind(cleaned) == TEAM_EXPENSE_KIND_CLAIM


async def pending_claim_advance_reservation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    employee: Any,
    *,
    exclude_invoice_id: int | None = None,
) -> Decimal:
    """Sum of open expense-claim totals for this employee (reserves float until posted)."""
    from app.services.purchase.team_expense_spend_service import normalize_employee_email
    from app.services.purchase.team_expense_validator import find_employee_by_sender

    stmt = select(
        Invoice.id,
        Invoice.total,
        Invoice.email_sender,
        Invoice.employee_email,
        Invoice.team_expense_kind,
    ).where(
        Invoice.tenant_id == tenant_id,
        Invoice.route_target == ROUTE_TEAM,
        Invoice.status.notin_(_PENDING_EXCLUDED_STATUSES),
        or_(
            Invoice.team_expense_kind == TEAM_EXPENSE_KIND_CLAIM,
            Invoice.team_expense_kind == _LEGACY_AGAINST_ADVANCE,
            Invoice.team_expense_kind.is_(None),
            Invoice.team_expense_kind == "",
        ),
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)

    total = Decimal("0")
    for _inv_id, amount, sender, emp_email, kind in (await session.execute(stmt)).all():
        if not _is_claim_kind(kind):
            continue
        identity = normalize_employee_email(emp_email) or sender
        if find_employee_by_sender([employee], identity) is None:
            continue
        if amount is None:
            continue
        total += Decimal(str(amount))
    return total if total > 0 else Decimal("0")


# Back-compat alias used by reports/tests.
pending_against_advance_total = pending_claim_advance_reservation


async def employee_available_advance(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: RuleBookConfigPayload,
    employee: Any,
    *,
    exclude_invoice_id: int | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (available, ledger_balance, pending_others) for claim netting.

    Available = ledger − open expense claims (conservative reservation).
    """
    emp_id = str(getattr(employee, "id", "") or "").strip()
    ledger = await employee_advance_balance(
        session,
        tenant_id,
        config,
        employee_id=emp_id,
        employee_parent_ledger=getattr(employee, "advance_parent_ledger", "") or "",
    )
    pending = await pending_claim_advance_reservation(
        session,
        tenant_id,
        employee,
        exclude_invoice_id=exclude_invoice_id,
    )
    available = ledger - pending
    if available < 0:
        available = Decimal("0")
    return available, ledger, pending


async def resolve_claim_advance_available(
    session: AsyncSession,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> Decimal | None:
    """Available Staff Advance float for expense-claim partial netting (None for advances)."""
    from app.schemas.rule_book_config import (
        TEAM_EXPENSE_KIND_ADVANCE,
        TEAM_EXPENSE_KIND_DIRECT,
        normalize_team_expense_kind,
    )
    from app.services.purchase.team_expense_validator import resolve_employee_for_sender

    kind = normalize_team_expense_kind(invoice.team_expense_kind)
    if kind == TEAM_EXPENSE_KIND_ADVANCE:
        return None
    if kind == TEAM_EXPENSE_KIND_DIRECT:
        return Decimal("0")
    if (invoice.route_target or "").strip() != ROUTE_TEAM:
        return None

    employee = await resolve_employee_for_sender(
        session,
        invoice.tenant_id,
        getattr(invoice, "employee_email", None) or invoice.email_sender,
    )
    if employee is None:
        return Decimal("0")
    available, _ledger, _pending = await employee_available_advance(
        session,
        invoice.tenant_id,
        config,
        employee,
        exclude_invoice_id=invoice.id,
    )
    return available
