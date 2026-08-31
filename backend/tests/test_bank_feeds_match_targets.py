"""Match-target picker helpers for bank feeds manual match."""

from decimal import Decimal

from app.services.bank_feeds.match_targets import format_match_target_label


def test_format_match_target_label_includes_party_and_invoice() -> None:
    label = format_match_target_label(
        party_name="Sharma Enterprises",
        invoice_no="INV-1042",
        amount=Decimal("12500.00"),
        currency="INR",
    )
    assert label == "Sharma Enterprises · INV-1042 · 12500.00 INR"
    assert "#" not in label


def test_format_match_target_label_without_invoice() -> None:
    label = format_match_target_label(
        party_name="Global Retail Corp",
        invoice_no=None,
        amount=25000,
        currency="INR",
    )
    assert label == "Global Retail Corp · 25000.00 INR"
