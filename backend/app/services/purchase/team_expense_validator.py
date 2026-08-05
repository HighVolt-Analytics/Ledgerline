"""Team expense policy checks (VR-TE*) at VALIDATE when route is Team Expenses."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department_budget import DepartmentBudget
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.schemas.master_data import EmployeeMasterResponse
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
    RuleBookConfigPayload,
    TeamExpenseRule,
    normalize_team_expense_kind,
)
from app.services.ingest.capture_channel import infer_capture_channel, normalize_phone
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM, load_config_for_tenant
from app.services.master_data.master_data_service import list_employee_masters
from app.services.purchase.po_reference import effective_po_reference
from app.services.purchase.team_expense_spend_service import (
    current_period_keys,
    department_period_consumed,
    employee_category_spend,
    employee_period_spend,
    normalize_employee_email,
)
from app.services.rule_book.rule_engine import EvalDocument, match_team_expense_rule
from app.services.rule_book.validator import ValidationResult
from app.tenant_settings import tenant_currency

_TE_DUP_EXCLUDED_STATUSES = (
    InvoiceStatus.REJECTED,
    InvoiceStatus.DUPLICATE_SKIPPED,
)
_TE_DUP_WINDOW = timedelta(hours=24)
_TE_AMOUNT_TOLERANCE = Decimal("0.01")


def document_type_spend_controls(
    config: RuleBookConfigPayload,
    document_type_code: str | None,
) -> tuple[bool, bool]:
    """Return (budget_control, advance_control) for a DT.

    New document types default both flags off. Invoices with no / unknown DT keep
    legacy enforcement (both on) so untyped Team Expense claims still check spend.
    """
    from app.services.classification.document_type_catalog import get_document_type_definition

    code = (document_type_code or "").strip().upper()
    if not code:
        return True, True
    definition = get_document_type_definition(
        code, document_types=config.document_types
    )
    if definition is None:
        return True, True
    return (
        bool(getattr(definition, "budget_control", False)),
        bool(getattr(definition, "advance_control", False)),
    )


async def resolve_employee_for_sender(
    session: AsyncSession,
    tenant_id: int,
    sender: str | None,
) -> EmployeeMasterResponse | None:
    employees = await list_employee_masters(session, tenant_id)
    return find_employee_by_sender(employees, sender)


def _sender_email_key(sender: str) -> str:
    """Normalize sender to a comparable email (handles ``Name <a@b.com>``)."""
    return normalize_employee_email(sender)


def find_employee_by_sender(
    employees: list[EmployeeMasterResponse] | list,
    sender: str | None,
) -> EmployeeMasterResponse | None:
    if not sender:
        return None
    key = _sender_email_key(sender)
    phone = normalize_phone(sender)
    for employee in employees:
        email = (employee.email or "").strip().lower()
        if email and email == key:
            return employee
        for field in (
            employee.whatsapp_number,
            employee.whatsapp_number_2 or "",
            employee.viber_number or "",
        ):
            digits = normalize_phone(field)
            if digits and phone and digits == phone:
                return employee
    return None


def resolve_team_expense_employee(
    employees: list[EmployeeMasterResponse] | list,
    *,
    employee_email: str | None,
    email_sender: str | None,
) -> EmployeeMasterResponse | None:
    """Prefer permanent invoice.employee_email; only guess from sender when unset."""
    stamped = normalize_employee_email(employee_email)
    if stamped:
        return find_employee_by_sender(employees, stamped)
    return find_employee_by_sender(employees, email_sender)


def _invoice_amount(data: InvoiceData) -> float | None:
    if data.total is None:
        return None
    return float(data.total)


def _limits(employee: EmployeeMasterResponse):
    return employee.spending_limits if hasattr(employee, "spending_limits") else employee.budget


def vr_te01_employee(
    employee: EmployeeMasterResponse | None,
    sender: str | None,
) -> ValidationResult:
    if not sender:
        return ValidationResult(
            "VR-TE01",
            False,
            "Team expense requires sender identity (email or mobile)",
        )
    if employee is None:
        return ValidationResult(
            "VR-TE01",
            False,
            f"No employee master matches sender {sender}",
        )
    return ValidationResult(
        "VR-TE01",
        True,
        f"Employee matched: {employee.name}",
    )


def vr_te02_budget(
    employee: EmployeeMasterResponse | None,
    amount: float | None,
    *,
    team_expense_kind: str | None = None,
    mtd_spent: float | None = None,
    qtd_spent: float | None = None,
    ytd_spent: float | None = None,
) -> ValidationResult:
    """Period spending limits — not applied to advance float."""
    if normalize_team_expense_kind(team_expense_kind) == TEAM_EXPENSE_KIND_ADVANCE:
        return ValidationResult(
            "VR-TE02",
            True,
            "Spending limit check skipped — advance requisition is float, not period spend",
            skipped=True,
        )
    if employee is None or amount is None:
        return ValidationResult("VR-TE02", True, "Spending limit check skipped")

    limits = _limits(employee)
    checks: list[tuple[str, float, float]] = [
        ("Monthly", float(limits.monthly or 0), float(mtd_spent if mtd_spent is not None else employee.mtd_spent or 0)),
        ("Quarterly", float(limits.quarterly or 0), float(qtd_spent if qtd_spent is not None else employee.qtd_spent or 0)),
        ("Annual", float(limits.annual or 0), float(ytd_spent if ytd_spent is not None else employee.ytd_spent or 0)),
    ]
    for label, cap, spent in checks:
        if cap <= 0:
            continue
        projected = spent + amount
        if projected > cap:
            return ValidationResult(
                "VR-TE02",
                False,
                (
                    f"{label} spending limit exceeded: spent {spent:.2f} + "
                    f"claim {amount:.2f} > cap {cap:.2f}"
                ),
            )
    return ValidationResult("VR-TE02", True, "Within employee spending limits")


_RECEIPT_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")


def has_receipt_attachment(raw_file_path: str | None) -> bool:
    path = (raw_file_path or "").lower()
    return any(path.endswith(ext) for ext in _RECEIPT_EXTENSIONS)


def vr_te03_receipt(
    team_rule: TeamExpenseRule | None,
    amount: float | None,
    *,
    has_receipt_file: bool = False,
    team_expense_kind: str | None = None,
) -> ValidationResult:
    """Merchant receipt policy — not applied to advance float requests."""
    if normalize_team_expense_kind(team_expense_kind) == TEAM_EXPENSE_KIND_ADVANCE:
        return ValidationResult(
            "VR-TE03",
            True,
            "Receipt check skipped — advance requisition is a funding request, not a merchant spend",
            skipped=True,
        )
    if team_rule is None or amount is None:
        return ValidationResult("VR-TE03", True, "Receipt policy check skipped")

    policy = team_rule.policy
    auto_below = policy.auto_approve_below
    if auto_below > 0 and amount < auto_below:
        return ValidationResult(
            "VR-TE03",
            True,
            f"Below auto-approve threshold ({auto_below:.2f}) — receipt optional",
        )

    threshold = max(policy.receipt_threshold, 0)
    requires_receipt = policy.require_receipt or (threshold > 0 and amount >= threshold)
    if not requires_receipt:
        return ValidationResult("VR-TE03", True, "Receipt not required for this amount")

    if has_receipt_file:
        return ValidationResult("VR-TE03", True, "Receipt attachment present")

    return ValidationResult(
        "VR-TE03",
        False,
        f"Receipt attachment required for amounts >= {threshold:.2f} (claim {amount:.2f})",
    )


def vr_te04_bank(
    employee: EmployeeMasterResponse | None,
    *,
    team_expense_kind: str | None = None,
) -> ValidationResult:
    """Bank required when cash is paid out (claim reimbursement or advance)."""
    if normalize_team_expense_kind(team_expense_kind) == TEAM_EXPENSE_KIND_AGAINST_ADVANCE:
        return ValidationResult(
            "VR-TE04",
            True,
            "Bank check skipped — expense against advance does not disburse cash",
            skipped=True,
        )
    if employee is None:
        return ValidationResult("VR-TE04", True, "Bank check skipped")
    account = (employee.bank.account_number or "").strip()
    if not account:
        kind = normalize_team_expense_kind(team_expense_kind)
        purpose = (
            "advance payout"
            if kind == TEAM_EXPENSE_KIND_ADVANCE
            else "reimbursement"
        )
        return ValidationResult(
            "VR-TE04",
            False,
            f"Employee bank account required for {purpose}",
        )
    return ValidationResult("VR-TE04", True, "Bank account on file")


def vr_te05_status(employee: EmployeeMasterResponse | None) -> ValidationResult:
    if employee is None:
        return ValidationResult("VR-TE05", True, "Status check skipped")
    status = (employee.status or "").strip().lower()
    if status in {"", "active"}:
        return ValidationResult("VR-TE05", True, "Employee active")
    if "suspend" in status:
        return ValidationResult("VR-TE05", False, f"Employee suspended: {employee.status}")
    if "pending" in status:
        return ValidationResult(
            "VR-TE05",
            False,
            f"Employee pending verification — complete HR verification before payment",
        )
    return ValidationResult(
        "VR-TE05",
        False,
        f"Employee status '{employee.status}' blocks team expense claims",
    )


def vr_te06_category_cap(
    employee: EmployeeMasterResponse | None,
    amount: float | None,
    team_rule: TeamExpenseRule | None,
    *,
    team_expense_kind: str | None = None,
    category_spent: float | None = None,
) -> ValidationResult:
    """Cumulative category spending limits — not applied to advance float."""
    if normalize_team_expense_kind(team_expense_kind) == TEAM_EXPENSE_KIND_ADVANCE:
        return ValidationResult(
            "VR-TE06",
            True,
            "Category limit skipped — advance requisition is float, not period spend",
            skipped=True,
        )
    if employee is None or amount is None or team_rule is None:
        return ValidationResult("VR-TE06", True, "Category limit check skipped")
    ledger = (team_rule.post_to.ledger or "").strip()
    limits = _limits(employee)
    if not ledger or not limits.categories:
        return ValidationResult("VR-TE06", True, "No category limit configured")

    spent = float(category_spent or 0)
    for cap in limits.categories:
        if cap.ledger.strip().lower() != ledger.lower():
            continue
        if cap.cap > 0 and (spent + amount) > cap.cap:
            return ValidationResult(
                "VR-TE06",
                False,
                (
                    f"Category limit exceeded for {ledger}: spent {spent:.2f} + "
                    f"claim {amount:.2f} > cap {cap.cap:.2f}"
                ),
            )
        return ValidationResult(
            "VR-TE06",
            True,
            f"Within {ledger} category limit (spent {spent:.2f})",
        )
    return ValidationResult("VR-TE06", True, "No matching category limit")


def vr_te07_advance_balance(
    employee: EmployeeMasterResponse | None,
    amount: float | None,
    *,
    team_expense_kind: str | None,
    advance_balance: float | None,
    ledger_balance: float | None = None,
    pending_reserved: float = 0,
) -> ValidationResult:
    """Expense against advance must not clear more than available (ledger − pending)."""
    if normalize_team_expense_kind(team_expense_kind) != TEAM_EXPENSE_KIND_AGAINST_ADVANCE:
        return ValidationResult("VR-TE07", True, "Advance balance check not applicable")
    if employee is None or amount is None:
        return ValidationResult("VR-TE07", True, "Advance balance check skipped")
    available = float(advance_balance) if advance_balance is not None else 0.0
    outstanding = float(ledger_balance) if ledger_balance is not None else available
    pending = max(float(pending_reserved or 0), 0.0)
    if amount > available:
        detail = f"outstanding advance {outstanding:.2f}"
        if pending > 0:
            detail += f", pending other claims {pending:.2f}"
        return ValidationResult(
            "VR-TE07",
            False,
            (
                f"Claim {amount:.2f} exceeds available advance {available:.2f} "
                f"({detail}) for {employee.name} — reduce the claim or post it as an expense claim"
            ),
        )
    msg = f"Within available advance ({available:.2f})"
    if pending > 0:
        msg += f" after reserving pending {pending:.2f}"
    return ValidationResult("VR-TE07", True, msg)


def vr_te08_department_budget(
    employee: EmployeeMasterResponse | None,
    amount: float | None,
    *,
    team_expense_kind: str | None = None,
    allocated: float | None = None,
    consumed: float | None = None,
    department: str | None = None,
    period_key: str | None = None,
) -> ValidationResult:
    """Department envelope — skipped when no budget row or for advances."""
    if normalize_team_expense_kind(team_expense_kind) == TEAM_EXPENSE_KIND_ADVANCE:
        return ValidationResult(
            "VR-TE08",
            True,
            "Department budget skipped — advance requisition is float, not department spend",
            skipped=True,
        )
    if employee is None or amount is None:
        return ValidationResult("VR-TE08", True, "Department budget check skipped")
    if allocated is None:
        return ValidationResult("VR-TE08", True, "No department budget configured")
    used = float(consumed or 0)
    cap = float(allocated)
    if cap <= 0:
        return ValidationResult("VR-TE08", True, "Department budget not enforced")
    projected = used + amount
    if projected > cap:
        dept = (department or employee.department or "").strip() or "department"
        period = (period_key or "").strip() or "period"
        return ValidationResult(
            "VR-TE08",
            False,
            (
                f"Department budget exceeded for {dept} ({period}): "
                f"consumed {used:.2f} + claim {amount:.2f} > allocated {cap:.2f}"
            ),
        )
    return ValidationResult(
        "VR-TE08",
        True,
        f"Within department budget (consumed {used:.2f} / {cap:.2f})",
    )


def vr_te09_duplicate_claim(
    *,
    employee_email: str | None,
    amount: float | None,
    duplicate: Invoice | None,
) -> ValidationResult:
    """Flag same employee + amount resubmitted within 24 hours."""
    if not (employee_email or "").strip() or amount is None:
        return ValidationResult("VR-TE09", True, "Duplicate claim check skipped")
    if duplicate is None:
        return ValidationResult(
            "VR-TE09",
            True,
            "No similar Team Expense claim in the last 24 hours",
        )
    ref = (duplicate.invoice_no or "").strip() or f"INV-{duplicate.id}"
    return ValidationResult(
        "VR-TE09",
        False,
        (
            f"Possible duplicate claim: same employee and amount "
            f"({float(amount):.2f}) as {ref} within 24 hours"
        ),
    )


def vr_te10_future_date(
    invoice_date: date | None,
    *,
    today: date | None = None,
) -> ValidationResult:
    """Block future-dated receipts on Team Expenses (fraud control)."""
    if invoice_date is None:
        return ValidationResult(
            "VR-TE10",
            True,
            "Future-date check skipped — no invoice date",
            skipped=True,
        )
    anchor = today or date.today()
    if invoice_date > anchor:
        return ValidationResult(
            "VR-TE10",
            False,
            f"Receipt/invoice date {invoice_date.isoformat()} cannot be in the future",
        )
    return ValidationResult("VR-TE10", True, "Invoice date is not in the future")


def vr_te11_currency(
    claim_currency: str | None,
    books_currency: str | None,
) -> ValidationResult:
    """Claim currency must match tenant books currency when both are set."""
    claim = (claim_currency or "").strip().upper()
    expected = (books_currency or "").strip().upper()
    if not claim or not expected:
        return ValidationResult(
            "VR-TE11",
            True,
            "Currency check skipped",
            skipped=True,
        )
    if claim != expected:
        return ValidationResult(
            "VR-TE11",
            False,
            (
                f"Claim currency {claim} does not match tenant books currency "
                f"{expected}"
            ),
        )
    return ValidationResult(
        "VR-TE11",
        True,
        f"Currency matches tenant books ({expected})",
    )


async def find_recent_similar_team_expense_claim(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    employee_email: str,
    amount: float | Decimal,
    invoice_date: date | None = None,
    exclude_invoice_id: int | None = None,
    as_of: datetime | None = None,
    window: timedelta = _TE_DUP_WINDOW,
) -> Invoice | None:
    """Find a TE claim with same employee + amount created in the lookback window.

    When the new claim has an invoice_date, a prior row matches if its date is the
    same or unset (amount/date/employee within 24h). Rejected / duplicate-skipped
    rows are ignored.
    """
    email = normalize_employee_email(employee_email)
    if not email:
        return None
    try:
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    except Exception:
        return None

    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    since = now - window

    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    total_expr = func.coalesce(Invoice.total, 0)
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tid,
            Invoice.route_target == ROUTE_TEAM,
            Invoice.status.notin_(_TE_DUP_EXCLUDED_STATUSES),
            Invoice.created_at >= since,
            func.lower(func.trim(func.coalesce(Invoice.employee_email, ""))) == email,
            func.abs(total_expr - amt) <= _TE_AMOUNT_TOLERANCE,
        )
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .limit(1)
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    if invoice_date is not None:
        stmt = stmt.where(
            or_(
                Invoice.invoice_date == invoice_date,
                Invoice.invoice_date.is_(None),
            )
        )

    return (await session.execute(stmt)).scalar_one_or_none()


async def _tenant_books_currency(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> str:
    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    tenant = await session.get(Tenant, tid)
    return tenant_currency(tenant)


async def _matching_department_budget(
    session: AsyncSession,
    tenant_id,
    *,
    department: str,
    gl_ledger: str,
    as_of: date,
) -> DepartmentBudget | None:
    dept = (department or "").strip()
    if not dept:
        return None
    keys = current_period_keys(as_of)
    ledger = (gl_ledger or "").strip()
    rows = (
        await session.execute(
            select(DepartmentBudget).where(
                DepartmentBudget.tenant_id == tenant_id,
                DepartmentBudget.period_kind.in_(("monthly", "quarterly", "annual")),
                DepartmentBudget.period_key.in_(list(keys.values())),
            )
        )
    ).scalars().all()
    dept_key = dept.casefold()
    for kind in ("monthly", "quarterly", "annual"):
        period_key = keys[kind]
        for prefer_gl in (ledger, ""):
            for row in rows:
                if (row.department or "").strip().casefold() != dept_key:
                    continue
                if row.period_kind != kind or row.period_key != period_key:
                    continue
                if (row.gl_ledger or "").strip() != prefer_gl:
                    continue
                return row
    return None


async def run_team_expense_validations(
    data: InvoiceData,
    session: AsyncSession,
    *,
    tenant_id: int,
    route_target: str | None,
    email_sender: str | None,
    config: RuleBookConfigPayload | None = None,
    has_receipt_file: bool = False,
    team_expense_kind: str | None = None,
    exclude_invoice_id: int | None = None,
    employee_email: str | None = None,
    invoice: object | None = None,
) -> list[ValidationResult]:
    if route_target != ROUTE_TEAM:
        return []

    if config is None:
        config = await load_config_for_tenant(session, tenant_id)

    employees = await list_employee_masters(session, tenant_id)
    stamped = employee_email
    if stamped is None and invoice is not None:
        stamped = getattr(invoice, "employee_email", None)

    employee = resolve_team_expense_employee(
        employees,
        employee_email=stamped,
        email_sender=email_sender,
    )
    # Stamp permanent email on the invoice when we have a match and a live invoice.
    if employee is not None and invoice is not None:
        canonical = normalize_employee_email(employee.email)
        if canonical and not normalize_employee_email(getattr(invoice, "employee_email", None)):
            invoice.employee_email = canonical
            stamped = canonical

    identity_for_vr = normalize_employee_email(stamped) or email_sender
    amount = _invoice_amount(data)

    doc = invoice_to_eval_document_from_data(data, email_sender)
    team_rule = match_team_expense_rule(
        doc,
        config.team_expense_rules,
        amount=amount,
    )

    as_of = date.today()
    if data.invoice_date is not None:
        as_of = data.invoice_date

    dt_code = None
    if invoice is not None:
        dt_code = getattr(invoice, "document_type_code", None)
    budget_control, advance_control = document_type_spend_controls(config, dt_code)

    mtd = qtd = ytd = None
    category_spent = None
    emp_email_key = normalize_employee_email(
        (employee.email if employee else None) or stamped
    )
    if (
        budget_control
        and employee is not None
        and emp_email_key
        and normalize_team_expense_kind(team_expense_kind) != TEAM_EXPENSE_KIND_ADVANCE
    ):
        spend = await employee_period_spend(
            session,
            tenant_id,
            emp_email_key,
            as_of=as_of,
            exclude_invoice_id=exclude_invoice_id,
        )
        mtd, qtd, ytd = spend.mtd, spend.qtd, spend.ytd
        ledger = (team_rule.post_to.ledger if team_rule else "") or ""
        if ledger.strip():
            category_spent = await employee_category_spend(
                session,
                tenant_id,
                emp_email_key,
                ledger,
                as_of=as_of,
                exclude_invoice_id=exclude_invoice_id,
            )

    available: float | None = None
    ledger_balance: float | None = None
    pending_reserved = 0.0
    if (
        advance_control
        and employee is not None
        and normalize_team_expense_kind(team_expense_kind) == TEAM_EXPENSE_KIND_AGAINST_ADVANCE
    ):
        from app.services.purchase.team_expense_advance_service import (
            employee_available_advance,
        )

        avail, ledger, pending = await employee_available_advance(
            session,
            tenant_id,
            config,
            employee,
            exclude_invoice_id=exclude_invoice_id,
        )
        available = float(avail)
        ledger_balance = float(ledger)
        pending_reserved = float(pending)

    dept_allocated = None
    dept_consumed = None
    dept_period_key = None
    dept_name = (employee.department if employee else "") or ""
    if (
        budget_control
        and employee is not None
        and normalize_team_expense_kind(team_expense_kind) != TEAM_EXPENSE_KIND_ADVANCE
    ):
        gl = (team_rule.post_to.ledger if team_rule else "") or ""
        dept_row = await _matching_department_budget(
            session,
            tenant_id,
            department=dept_name,
            gl_ledger=gl,
            as_of=as_of,
        )
        if dept_row is not None:
            dept_allocated = float(dept_row.allocated or 0)
            dept_period_key = dept_row.period_key
            dept_emails = [
                normalize_employee_email(e.email)
                for e in employees
                if (e.department or "").strip().casefold() == dept_name.strip().casefold()
            ]
            dept_consumed = await department_period_consumed(
                session,
                tenant_id,
                department=dept_name,
                period_kind=dept_row.period_kind,
                period_key=dept_row.period_key,
                gl_ledger=dept_row.gl_ledger or "",
                employee_emails=dept_emails,
                exclude_invoice_id=exclude_invoice_id,
            )

    def _budget_result(result: ValidationResult) -> ValidationResult:
        if budget_control:
            return result
        return ValidationResult(
            result.rule,
            True,
            "Budget control off for this document type — employee budget not checked",
            skipped=True,
        )

    def _advance_result(result: ValidationResult) -> ValidationResult:
        if advance_control:
            return result
        return ValidationResult(
            result.rule,
            True,
            "Advance control off for this document type — employee advance not checked",
            skipped=True,
        )

    results = [
        vr_te01_employee(employee, identity_for_vr),
        _budget_result(
            vr_te02_budget(
                employee,
                amount,
                team_expense_kind=team_expense_kind,
                mtd_spent=mtd,
                qtd_spent=qtd,
                ytd_spent=ytd,
            )
        ),
        vr_te03_receipt(
            team_rule,
            amount,
            has_receipt_file=has_receipt_file,
            team_expense_kind=team_expense_kind,
        ),
        vr_te04_bank(employee, team_expense_kind=team_expense_kind),
        vr_te05_status(employee),
        _budget_result(
            vr_te06_category_cap(
                employee,
                amount,
                team_rule,
                team_expense_kind=team_expense_kind,
                category_spent=category_spent,
            )
        ),
        _advance_result(
            vr_te07_advance_balance(
                employee,
                amount,
                team_expense_kind=team_expense_kind,
                advance_balance=available,
                ledger_balance=ledger_balance,
                pending_reserved=pending_reserved,
            )
        ),
        _budget_result(
            vr_te08_department_budget(
                employee,
                amount,
                team_expense_kind=team_expense_kind,
                allocated=dept_allocated,
                consumed=dept_consumed,
                department=dept_name,
                period_key=dept_period_key,
            )
        ),
    ]

    emp_key = emp_email_key or normalize_employee_email(stamped) or ""
    duplicate = None
    if emp_key and amount is not None:
        duplicate = await find_recent_similar_team_expense_claim(
            session,
            tenant_id,
            employee_email=emp_key,
            amount=amount,
            invoice_date=data.invoice_date,
            exclude_invoice_id=exclude_invoice_id,
        )
    books_ccy = await _tenant_books_currency(session, tenant_id)
    claim_ccy = None
    if invoice is not None:
        claim_ccy = getattr(invoice, "currency", None)
    if not (claim_ccy or "").strip() and getattr(data, "currency", None):
        claim_ccy = data.currency

    results.extend(
        [
            vr_te09_duplicate_claim(
                employee_email=emp_key or None,
                amount=amount,
                duplicate=duplicate,
            ),
            vr_te10_future_date(data.invoice_date),
            vr_te11_currency(claim_ccy, books_ccy),
        ]
    )
    return results


def invoice_to_eval_document_from_data(
    data: InvoiceData,
    email_sender: str | None,
) -> EvalDocument:
    """Build EvalDocument from parsed invoice data for team rule matching."""
    lines = tuple(
        (line.description or "").strip()
        for line in data.line_items
        if (line.description or "").strip()
    )
    invoice_no = data.invoice_no or ""
    return EvalDocument(
        id=invoice_no or "draft",
        doc_number=invoice_no or "draft",
        invoice_no=invoice_no,
        vendor=data.vendor or "",
        abn=data.abn,
        po=effective_po_reference(data.po_reference),
        lines=lines,
        email_from=email_sender,
        capture_channel=infer_capture_channel(email_sender),
        document_type="invoice",
        address=data.billing_address,
        bank_bsb=data.bank_bsb,
        bank_account=data.bank_account,
    )
