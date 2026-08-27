"""Team expense kind inference from catalogue titles."""

from app.services.purchase.team_expense_kind_service import (
    infer_team_expense_kind_from_labels,
    reconcile_team_expense_kind_for_document_type,
)


def test_payment_voucher_title_infers_direct_payment() -> None:
    assert infer_team_expense_kind_from_labels("Payment Voucher") == "direct_payment"
    assert infer_team_expense_kind_from_labels("Direct payment request") == "direct_payment"


def test_advance_vs_expense_against_advance_phrases_are_opposites() -> None:
    assert infer_team_expense_kind_from_labels("Advance Requisition") == (
        "advance_requisition"
    )
    assert infer_team_expense_kind_from_labels("Cash Advance Requisition") == (
        "advance_requisition"
    )
    assert infer_team_expense_kind_from_labels("Expense against advance") == (
        "expense_claim"
    )
    # Settlement phrase wins when both appear in the same blob.
    assert infer_team_expense_kind_from_labels(
        "Advance Requisition",
        "Expense against advance",
    ) == "expense_claim"


def test_reconcile_fills_empty_pin_from_payment_voucher_title() -> None:
    assert (
        reconcile_team_expense_kind_for_document_type(
            title="Payment Voucher",
            configured="",
        )
        == "direct_payment"
    )
