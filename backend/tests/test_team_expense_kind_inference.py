"""Team expense kind inference from catalogue titles."""

from app.services.purchase.team_expense_kind_service import (
    infer_team_expense_kind_from_labels,
    reconcile_team_expense_kind_for_document_type,
)


def test_payment_voucher_title_infers_direct_payment() -> None:
    assert infer_team_expense_kind_from_labels("Payment Voucher") == "direct_payment"
    assert infer_team_expense_kind_from_labels("Direct payment request") == "direct_payment"


def test_reconcile_fills_empty_pin_from_payment_voucher_title() -> None:
    assert (
        reconcile_team_expense_kind_for_document_type(
            title="Payment Voucher",
            configured="",
        )
        == "direct_payment"
    )
