"""Team expense policy: mapping-phase approval gate and manual approve checks."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes as orm_attributes

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import RuleBookConfigPayload, TeamExpenseRule
from app.services.audit.audit_service import log_event
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_APPROVAL, ROUTE_TEAM, load_config_for_tenant
from app.services.rule_book.rule_engine import match_team_expense_rule
from app.services.purchase.team_expense_validator import (
    has_receipt_attachment,
    invoice_to_eval_document_from_data,
    vr_te03_receipt,
)


def team_rule_for_invoice(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> TeamExpenseRule | None:
    amount = float(invoice.total) if invoice.total is not None else None
    state = orm_attributes.instance_state(invoice)
    if "line_items" in state.unloaded:
        parsed_lines: list[ParsedLineItem] = []
    else:
        parsed_lines = [
            ParsedLineItem(description=line.description, amount=line.amount)
            for line in invoice.line_items
        ]
    data = InvoiceData(
        vendor=invoice.vendor,
        abn=invoice.abn,
        invoice_no=invoice.invoice_no,
        po_reference=invoice.po_reference,
        total=invoice.total,
        line_items=parsed_lines,
    )
    doc = invoice_to_eval_document_from_data(data, invoice.email_sender)
    return match_team_expense_rule(
        doc,
        config.team_expense_rules,
        amount=amount,
    )


async def has_manager_approval(session: AsyncSession, invoice_id: int) -> bool:
    from app.services.approval.approval_quorum_service import quorum_met

    invoice = await session.get(Invoice, invoice_id)
    if invoice is not None and isinstance(getattr(invoice, "approval_chain", None), dict):
        return quorum_met(invoice.approval_chain)

    row = (
        await session.execute(
            select(AuditLog.id)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.event == "invoice_approved",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


def has_soft_budget_overrun(invoice: Invoice) -> bool:
    """True when VR-TE08 soft-failed (over budget → manager override path)."""
    import json

    raw = getattr(invoice, "validation_results", None)
    if not raw:
        return False
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(rows, list):
        return False
    return any(
        isinstance(row, dict)
        and row.get("rule") == "VR-TE08"
        and not row.get("passed")
        and not row.get("skipped")
        and (row.get("severity") or "block") == "warn"
        for row in rows
    )


def requires_manual_approval(
    invoice: Invoice,
    team_rule: TeamExpenseRule | None,
    *,
    manager_approved: bool,
    playbook_auto_approve_below: float | None = None,
    soft_budget_overrun: bool = False,
) -> bool:
    """Claims at/above auto_approve_below need manager approval before posting.

    Advance requisitions always require manager approval (cash out / float) — never
    touchless regardless of threshold.

    Soft GL budget overruns always hold for manager, even below auto-approve amount.

    For expense claims, threshold preference:
    1. Matched ``team_expense_rules`` policy (category rule)
    2. DT playbook ``Require approval at/above ($)`` when Manager gate is active
    3. No threshold configured → hold for manager (Manager gate default)
    """
    if invoice.route_target != ROUTE_TEAM or manager_approved:
        return False

    from app.schemas.rule_book_config import (
        TEAM_EXPENSE_KIND_ADVANCE,
        normalize_team_expense_kind,
    )

    if soft_budget_overrun:
        return True

    if normalize_team_expense_kind(invoice.team_expense_kind) == TEAM_EXPENSE_KIND_ADVANCE:
        return True

    if invoice.total is None:
        return True

    amount = float(invoice.total)
    auto_below: float | None = None
    if team_rule is not None:
        auto_below = float(team_rule.policy.auto_approve_below or 0) or None
        if auto_below is not None and auto_below <= 0:
            auto_below = None
    elif playbook_auto_approve_below is not None:
        auto_below = float(playbook_auto_approve_below)

    if auto_below is not None and auto_below > 0 and amount < auto_below:
        return False
    # Manager gate with no auto-approve threshold (or amount at/above threshold) → hold.
    return True


async def apply_team_expense_approval_gate(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """
    Hold team claims for manager approval after mapping.

    Advance requisitions always hold. Expense claims hold when at or above the
    auto-approve threshold (or when no threshold is configured). Soft GL budget
    overruns always hold for manager override.

    Returns True when the invoice is held (status set to exception).
    """
    if invoice.route_target != ROUTE_TEAM:
        return False

    config = await load_config_for_tenant(session, invoice.tenant_id)
    team_rule = team_rule_for_invoice(invoice, config)
    approved = await has_manager_approval(session, invoice.id)
    soft_budget = has_soft_budget_overrun(invoice)

    playbook_auto_approve_below: float | None = None
    dt_code = (invoice.document_type_code or "").strip().upper()
    if dt_code:
        from app.services.classification.document_type_catalog import (
            get_document_type_definition,
        )
        from app.services.classification.document_type_playbook_profile_service import (
            effective_approval_policy,
        )

        definition = get_document_type_definition(
            dt_code, document_types=config.document_types
        )
        if definition is not None:
            policy = effective_approval_policy(definition)
            if policy.mode == "manager_gate":
                playbook_auto_approve_below = policy.auto_approve_below

    if not requires_manual_approval(
        invoice,
        team_rule,
        manager_approved=approved,
        playbook_auto_approve_below=playbook_auto_approve_below,
        soft_budget_overrun=soft_budget,
    ):
        threshold = (
            (team_rule.policy.auto_approve_below if team_rule else None)
            or playbook_auto_approve_below
        )
        if (
            threshold is not None
            and float(threshold) > 0
            and invoice.total is not None
            and float(invoice.total) < float(threshold)
        ):
            from app.services.purchase.team_expense_validator import resolve_employee_for_sender

            employee = await resolve_employee_for_sender(
                session,
                invoice.tenant_id,
                invoice.email_sender,
            )
            await log_event(
                session,
                "team_expense_auto_approved",
                invoice_id=invoice.id,
                detail={
                    "amount": float(invoice.total),
                    "threshold": float(threshold),
                    "merchant": invoice.vendor,
                    "employee_name": employee.name if employee else None,
                    "source": "team_rule" if team_rule else "playbook",
                },
            )
            await session.flush()
        return False

    from app.schemas.rule_book_config import (
        TEAM_EXPENSE_KIND_ADVANCE,
        normalize_team_expense_kind,
    )

    kind = normalize_team_expense_kind(invoice.team_expense_kind)
    if soft_budget:
        hold_reason = "over_budget_requires_approval"
    elif kind == TEAM_EXPENSE_KIND_ADVANCE:
        hold_reason = "advance_requisition_requires_approval"
    else:
        hold_reason = "above_auto_approve_threshold"

    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_PENDING_APPROVAL
    await log_event(
        session,
        "team_expense_approval_required",
        invoice_id=invoice.id,
        detail={
            "amount": float(invoice.total) if invoice.total is not None else None,
            "auto_approve_below": (
                team_rule.policy.auto_approve_below
                if team_rule
                else playbook_auto_approve_below
            ),
            "rule_id": team_rule.id if team_rule else None,
            "reason": hold_reason,
            "team_expense_kind": kind,
            "soft_budget_overrun": soft_budget,
        },
    )
    await session.flush()
    return True


async def assert_team_expense_approvable(
    session: AsyncSession,
    invoice: Invoice,
) -> None:
    """Raise ValueError when team policy blocks manual approval."""
    if invoice.route_target != ROUTE_TEAM:
        return

    config = await load_config_for_tenant(session, invoice.tenant_id)
    team_rule = team_rule_for_invoice(invoice, config)
    amount = float(invoice.total) if invoice.total is not None else None
    has_file = has_receipt_attachment(invoice.raw_file_path)

    receipt = vr_te03_receipt(
        team_rule,
        amount,
        has_receipt_file=has_file,
        team_expense_kind=invoice.team_expense_kind,
    )
    if not receipt.passed:
        raise ValueError(receipt.message)
