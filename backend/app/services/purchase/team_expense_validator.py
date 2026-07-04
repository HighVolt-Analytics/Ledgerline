"""Team expense policy checks (VR-TE*) at VALIDATE when route is Team Expenses."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.master_data import EmployeeMasterResponse
from app.schemas.rule_book_config import RuleBookConfigPayload, TeamExpenseRule
from app.services.ingest.capture_channel import infer_capture_channel, normalize_phone
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM, load_config_for_tenant
from app.services.master_data.master_data_service import list_employee_masters
from app.services.purchase.po_reference import effective_po_reference
from app.services.rule_book.rule_engine import EvalDocument, match_team_expense_rule
from app.services.rule_book.validator import ValidationResult


async def resolve_employee_for_sender(
    session: AsyncSession,
    tenant_id: int,
    sender: str | None,
) -> EmployeeMasterResponse | None:
    employees = await list_employee_masters(session, tenant_id)
    return _find_employee_by_sender(employees, sender)


def _find_employee_by_sender(
    employees: list[EmployeeMasterResponse],
    sender: str | None,
) -> EmployeeMasterResponse | None:
    if not sender:
        return None
    key = sender.strip().lower()
    phone = normalize_phone(sender)
    for employee in employees:
        email = (employee.email or "").strip().lower()
        if email and email == key:
            return employee
        for field in (employee.whatsapp_number, employee.viber_number or ""):
            digits = normalize_phone(field)
            if digits and phone and digits == phone:
                return employee
    return None


def _invoice_amount(data: InvoiceData) -> float | None:
    if data.total is None:
        return None
    return float(data.total)


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
) -> ValidationResult:
    if employee is None or amount is None:
        return ValidationResult("VR-TE02", True, "Budget check skipped")

    checks: list[tuple[str, float, float]] = [
        ("Monthly", employee.budget.monthly, employee.mtd_spent),
        ("Quarterly", employee.budget.quarterly, employee.qtd_spent),
        ("Annual", employee.budget.annual, employee.ytd_spent),
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
                    f"{label} budget exceeded: spent {spent:.2f} + "
                    f"claim {amount:.2f} > cap {cap:.2f}"
                ),
            )
    return ValidationResult("VR-TE02", True, "Within employee budget caps")


_RECEIPT_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")


def has_receipt_attachment(raw_file_path: str | None) -> bool:
    path = (raw_file_path or "").lower()
    return any(path.endswith(ext) for ext in _RECEIPT_EXTENSIONS)


def vr_te03_receipt(
    team_rule: TeamExpenseRule | None,
    amount: float | None,
    *,
    has_receipt_file: bool = False,
) -> ValidationResult:
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


def vr_te04_bank(employee: EmployeeMasterResponse | None) -> ValidationResult:
    if employee is None:
        return ValidationResult("VR-TE04", True, "Bank check skipped")
    account = (employee.bank.account_number or "").strip()
    if not account:
        return ValidationResult(
            "VR-TE04",
            False,
            "Employee bank account required for reimbursement",
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
) -> ValidationResult:
    if employee is None or amount is None or team_rule is None:
        return ValidationResult("VR-TE06", True, "Category cap check skipped")
    ledger = (team_rule.post_to.ledger or "").strip()
    if not ledger or not employee.budget.categories:
        return ValidationResult("VR-TE06", True, "No category cap configured")

    for cap in employee.budget.categories:
        if cap.ledger.strip().lower() != ledger.lower():
            continue
        if cap.cap > 0 and amount > cap.cap:
            return ValidationResult(
                "VR-TE06",
                False,
                f"Category cap exceeded for {ledger}: {amount:.2f} > {cap.cap:.2f}",
            )
        return ValidationResult("VR-TE06", True, f"Within {ledger} category cap")
    return ValidationResult("VR-TE06", True, "No matching category cap")


async def run_team_expense_validations(
    data: InvoiceData,
    session: AsyncSession,
    *,
    tenant_id: int,
    route_target: str | None,
    email_sender: str | None,
    config: RuleBookConfigPayload | None = None,
    has_receipt_file: bool = False,
) -> list[ValidationResult]:
    if route_target != ROUTE_TEAM:
        return []

    if config is None:
        config = await load_config_for_tenant(session, tenant_id)

    employees = await list_employee_masters(session, tenant_id)
    employee = _find_employee_by_sender(employees, email_sender)
    amount = _invoice_amount(data)

    doc = invoice_to_eval_document_from_data(data, email_sender)
    team_rule = match_team_expense_rule(
        doc,
        config.team_expense_rules,
        amount=amount,
    )

    return [
        vr_te01_employee(employee, email_sender),
        vr_te02_budget(employee, amount),
        vr_te03_receipt(team_rule, amount, has_receipt_file=has_receipt_file),
        vr_te04_bank(employee),
        vr_te05_status(employee),
        vr_te06_category_cap(employee, amount, team_rule),
    ]


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
