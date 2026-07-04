"""Vendor detection outcomes for Expenses Management (amount-gated hold)."""

from __future__ import annotations

from app.schemas.rule_book_config import RuleBookConfigPayload

EVAL_UNMATCHED_EXPENSE_VENDOR = "unmatched_expense_vendor"
EXPENSE_ROUTE = "Expenses Management"
TEAM_ROUTE = "Team Expenses"
PENDING_VENDOR = "pending_vendor"


def expense_vendor_hold_above(config: RuleBookConfigPayload) -> float:
    return float(config.vendor_detection_config.expense_vendor_hold_above)


def vendor_detection_evaluation_status(
    *,
    route_target: str | None,
    confidence: float,
    threshold: int,
    known_master: object | None,
    amount: float | None,
    hold_above: float,
    registration_required: bool = True,
) -> str | None:
    """
    Return evaluation_status from vendor detection, or None when vendor check passes.

    Expenses Management (architecture §3b):
    - confidence >= threshold → no vendor flag
    - confidence < threshold and amount <= hold_above → unmatched_expense_vendor
    - confidence < threshold and amount > hold_above → pending_vendor (hold)
    Team Expenses / Vault / non-actionable types: never vendor-flagged (registration_required=False).
    Other payable routes: pending_vendor when below threshold and unknown.
    """
    if not registration_required:
        return None
    route = (route_target or "").strip()
    if known_master or confidence >= threshold:
        return None
    if route == TEAM_ROUTE:
        return None
    if route == EXPENSE_ROUTE:
        if amount is not None and amount > hold_above:
            return PENDING_VENDOR
        return EVAL_UNMATCHED_EXPENSE_VENDOR
    return PENDING_VENDOR


def is_unmatched_expense_vendor_status(evaluation_status: str | None) -> bool:
    return (evaluation_status or "").strip() == EVAL_UNMATCHED_EXPENSE_VENDOR
