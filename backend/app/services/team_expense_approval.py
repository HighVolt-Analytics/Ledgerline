"""Team expense policy enforcement at approval time (architecture §6)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.rule_book_config import TeamExpenseRule
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice_evaluation_service import ROUTE_TEAM, load_config_for_org
from app.services.rule_engine import match_team_expense_rule
from app.services.team_expense_validator import (
    invoice_to_eval_document_from_data,
    vr_te03_receipt,
)

_RECEIPT_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")


def _has_receipt_file(invoice: Invoice) -> bool:
    path = (invoice.raw_file_path or "").lower()
    return any(path.endswith(ext) for ext in _RECEIPT_EXTENSIONS)


def team_expense_auto_approve_eligible(
    results: list,
    *,
    route_target: str | None,
    amount: float | None,
    team_rule: TeamExpenseRule | None,
) -> bool:
    """Small claims below auto_approve_below may bypass receipt failure only."""
    if route_target != ROUTE_TEAM or team_rule is None or amount is None:
        return False
    threshold = team_rule.policy.auto_approve_below
    if threshold <= 0 or amount >= threshold:
        return False

    failing = [r for r in results if not r.passed and not getattr(r, "skipped", False)]
    if not failing:
        return True
    if len(failing) == 1 and failing[0].rule == "VR-TE03":
        return True
    return False


async def assert_team_expense_approvable(
    session: AsyncSession,
    invoice: Invoice,
) -> None:
    """Raise ValueError when team policy blocks manual approval."""
    if invoice.route_target != ROUTE_TEAM:
        return

    config = load_config_for_org(invoice.org_id)
    amount = float(invoice.total) if invoice.total is not None else None
    data = InvoiceData(
        vendor=invoice.vendor,
        abn=invoice.abn,
        invoice_no=invoice.invoice_no,
        po_reference=invoice.po_reference,
        total=invoice.total,
        line_items=[
            ParsedLineItem(description=line.description, amount=line.amount)
            for line in invoice.line_items
        ],
    )
    doc = invoice_to_eval_document_from_data(data, invoice.email_sender)
    team_rule = match_team_expense_rule(
        doc,
        config.team_expense_rules,
        amount=amount,
    )
    if team_rule is None:
        return

    receipt = vr_te03_receipt(team_rule, amount)
    if not receipt.passed:
        if not _has_receipt_file(invoice):
            raise ValueError(receipt.message)

    policy = team_rule.policy
    if policy.auto_approve_below > 0 and amount is not None and amount < policy.auto_approve_below:
        return

    if policy.require_receipt and amount is not None and amount >= policy.receipt_threshold:
        if not _has_receipt_file(invoice):
            raise ValueError(
                f"Receipt image or PDF required for claims >= {policy.receipt_threshold:.2f}"
            )

