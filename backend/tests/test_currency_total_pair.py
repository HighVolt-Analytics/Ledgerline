"""Multi-currency (currency, total) pairing — dual-column and FX edge cases."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_data import InvoiceData
from app.services.extraction.field_grounding_service import ground_invoice_scalars
from app.services.invoice.vision_header_reconcile import apply_vision_header_text_reconcile
from app.services.shared.currency_total_pair import (
    detect_multi_currency_in_text,
    reconcile_currency_total_pair,
)
from app.tenant_ids import TESTING_TENANT_UUID

_PAD = "\nEnough body text so grounding length threshold is satisfied for checks.\n"


def test_dell_style_dual_column_swaps_sgd_total_to_usd() -> None:
    """Currency=USD must not keep the SGD column grand total."""
    text = (
        "Dell Global B.V. (Singapore Branch)\n"
        "Tax Invoice 4401413318\n"
        "SGD          USD\n"
        "Subtotal     5,701.86    4,440.00\n"
        "GST 9%         513.16      399.60\n"
        "Total Amount 6,215.02    4,839.60\n"
        + _PAD
    )
    assert detect_multi_currency_in_text(text) is True
    result = reconcile_currency_total_pair(
        currency="USD",
        total=Decimal("6215.02"),
        text=text,
    )
    assert result.currency == "USD"
    assert result.total == Decimal("4839.60")
    assert result.swapped is True
    assert result.multi_currency is True


def test_dell_style_apply_vision_reconcile() -> None:
    text = (
        "Dell Global B.V. (Singapore Branch)\n"
        "Tax Invoice\n"
        "SGD USD\n"
        "Subtotal 5,701.86 4,440.00\n"
        "GST 9% 513.16 399.60\n"
        "Total Amount 6,215.02 4,839.60\n"
        + _PAD
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="USD",
        total=Decimal("6215.02"),
        extracted_fields={"currency": "USD", "total": "6215.02"},
    )
    detail = apply_vision_header_text_reconcile(inv, text)
    assert inv.currency == "USD"
    assert inv.total == Decimal("4839.60")
    assert detail.get("multi_currency") is True
    assert "swapped_total" in str(detail.get("pair_reason") or detail.get("total_reason"))


def test_local_primary_plus_usd_equivalent() -> None:
    text = (
        "Invoice\n"
        "Total AUD 1,100.00\n"
        "Total USD 720.00 (at 1 USD = 1.528 AUD)\n"
        + _PAD
    )
    result = reconcile_currency_total_pair(
        currency="AUD",
        total=Decimal("720.00"),
        text=text,
    )
    assert result.currency == "AUD"
    assert result.total == Decimal("1100.00")
    assert result.swapped is True


def test_usd_invoice_ignores_bank_sgd_box_when_pair_ok() -> None:
    text = (
        "Commercial Invoice\n"
        "Total Amount US$4,839.60\n"
        "Bank remittance details\n"
        "Bank Currency: SGD\n"
        "Remit SGD 6,215.02\n"
        + _PAD
    )
    result = reconcile_currency_total_pair(
        currency="USD",
        total=Decimal("4839.60"),
        text=text,
    )
    assert result.currency == "USD"
    assert result.total == Decimal("4839.60")
    assert result.swapped is False


def test_usd_invoice_bank_sgd_amount_mistaken_as_total_swaps_back() -> None:
    text = (
        "Commercial Invoice\n"
        "Total Amount US$4,839.60\n"
        "Please remit SGD 6,215.02 to our SGD account\n"
        + _PAD
    )
    result = reconcile_currency_total_pair(
        currency="USD",
        total=Decimal("6215.02"),
        text=text,
    )
    assert result.currency == "USD"
    assert result.total == Decimal("4839.60")
    assert result.swapped is True


def test_single_currency_unchanged() -> None:
    text = "MongoDB Limited\nSubtotal US$33.70\nTotal US$37.08\n" + _PAD
    result = reconcile_currency_total_pair(
        currency="USD",
        total=Decimal("37.08"),
        text=text,
    )
    assert result.currency == "USD"
    assert result.total == Decimal("37.08")
    assert result.multi_currency is False
    assert result.reason == "single_currency_unchanged"


def test_inline_iso_on_total_line() -> None:
    text = (
        "Tax Invoice\n"
        "Total Amount 6,215.02 SGD  4,839.60 USD\n"
        + _PAD
    )
    result = reconcile_currency_total_pair(
        currency="USD",
        total=Decimal("6215.02"),
        text=text,
    )
    assert result.total == Decimal("4839.60")
    assert result.swapped is True


def test_clears_when_no_amount_for_selected_currency() -> None:
    text = (
        "Summary\n"
        "Total Amount SGD 6,215.02\n"
        "Reference FX USD shown elsewhere without a payable total\n"
        "Currency note: USD\n"
        + _PAD
    )
    # SGD tagged total only; currency=USD with SGD amount → clear rather than keep mismatch
    result = reconcile_currency_total_pair(
        currency="USD",
        total=Decimal("6215.02"),
        text=text,
    )
    assert result.currency == "USD"
    assert result.total is None
    assert result.swapped is True


def test_empty_currency_filled_from_unique_tag() -> None:
    text = "Invoice\nTotal Amount US$37.08\n" + _PAD
    result = reconcile_currency_total_pair(
        currency="",
        total=Decimal("37.08"),
        text=text,
    )
    assert result.currency == "USD"
    assert result.total == Decimal("37.08")


def test_ground_invoice_scalars_fixes_dual_column() -> None:
    text = (
        "Dell Global B.V. (Singapore Branch)\n"
        "Tax Invoice 4401413318\n"
        "SGD USD\n"
        "Subtotal 5,701.86 4,440.00\n"
        "GST 9% 513.16 399.60\n"
        "Total Amount 6,215.02 4,839.60\n"
        + _PAD
    )
    parsed = InvoiceData(
        currency="USD",
        total=Decimal("6215.02"),
        document_text=text,
    )
    grounded = ground_invoice_scalars(parsed, text)
    assert grounded.currency == "USD"
    assert grounded.total == Decimal("4839.60")


def test_pair_confirmed_when_already_correct() -> None:
    text = (
        "SGD USD\n"
        "Total Amount 6,215.02 4,839.60\n"
        + _PAD
    )
    result = reconcile_currency_total_pair(
        currency="USD",
        total=Decimal("4839.60"),
        text=text,
    )
    assert result.total == Decimal("4839.60")
    assert result.swapped is False
    assert result.reason == "pair_confirmed"
