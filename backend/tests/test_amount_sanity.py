from decimal import Decimal

from app.services.extraction.gst_rate import parse_gst_rate_percent, resolve_gst_rate_percent
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.shared.amount_sanity import (
    plausible_confidence,
    plausible_gst_rate_percent,
    plausible_money,
    plausible_qty,
    sanitize_parsed_line_item,
)


def test_plausible_money_rejects_abn_sized_values() -> None:
    assert plausible_money(Decimal("52500944661")) is None
    assert plausible_money(Decimal("13.96")) == Decimal("13.96")


def test_plausible_qty_rejects_id_sized_values() -> None:
    assert plausible_qty(Decimal("52500944661")) is None
    assert plausible_qty(Decimal("10.5")) == Decimal("10.5")


def test_plausible_gst_rate_rejects_overflow_and_garbage() -> None:
    assert plausible_gst_rate_percent(Decimal("10")) == Decimal("10.00")
    assert plausible_gst_rate_percent(Decimal("150")) is None
    assert plausible_gst_rate_percent(Decimal("1000")) is None


def test_parse_gst_rate_rejects_absurd_explicit_values() -> None:
    assert parse_gst_rate_percent("52500944661") is None


def test_resolve_gst_rate_rejects_bad_inference() -> None:
    data = InvoiceData(subtotal=Decimal("0.01"), gst=Decimal("52500944661"))
    assert resolve_gst_rate_percent(data) is None


def test_plausible_confidence_normalizes_percent_scale() -> None:
    assert plausible_confidence(91) == Decimal("0.9100")
    assert plausible_confidence(0.91) == Decimal("0.9100")
    assert plausible_confidence(9100) == Decimal("0.9100")
    assert plausible_confidence(999999) is None


def test_sanitize_parsed_line_item_rejects_overflowing_amounts() -> None:
    cleaned = sanitize_parsed_line_item(
        ParsedLineItem(
            description="Widget",
            qty=Decimal("1"),
            unit_price=Decimal("52500944661"),
            amount=Decimal("52500944661"),
        )
    )
    assert cleaned.unit_price is None
    assert cleaned.amount is None


def test_sanitize_parsed_line_item_clamps_product_overflow() -> None:
    cleaned = sanitize_parsed_line_item(
        ParsedLineItem(
            description="Widget",
            qty=Decimal("100000"),
            unit_price=Decimal("100000"),
            amount=None,
        )
    )
    assert cleaned.amount is None
