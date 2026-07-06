from decimal import Decimal

from app.services.extraction.gst_rate import (
    expected_gst_amount,
    invoice_gst_rate_fraction,
    parse_gst_rate_percent,
    resolve_gst_rate_percent,
)
from app.services.invoice.invoice_data import InvoiceData


def test_parse_gst_rate_percent_from_percent_string() -> None:
    assert parse_gst_rate_percent("10%") == Decimal("10.00")
    assert parse_gst_rate_percent("15.5%") == Decimal("15.50")


def test_parse_gst_rate_percent_from_number() -> None:
    assert parse_gst_rate_percent(10) == Decimal("10.00")
    assert parse_gst_rate_percent("18") == Decimal("18.00")


def test_parse_gst_rate_percent_from_fraction() -> None:
    assert parse_gst_rate_percent(0.1) == Decimal("10.00")
    assert parse_gst_rate_percent("0.15") == Decimal("15.00")


def test_resolve_gst_rate_percent_from_explicit_field() -> None:
    data = InvoiceData(gst_rate=Decimal("15"), subtotal=Decimal("100"), gst=Decimal("15"))
    assert resolve_gst_rate_percent(data) == Decimal("15.00")


def test_resolve_gst_rate_percent_infers_from_amounts() -> None:
    data = InvoiceData(subtotal=Decimal("1000"), gst=Decimal("100"))
    assert resolve_gst_rate_percent(data) == Decimal("10.00")


def test_resolve_gst_rate_percent_zero_rated() -> None:
    data = InvoiceData(subtotal=Decimal("500"), gst=Decimal("0"))
    assert resolve_gst_rate_percent(data) == Decimal("0.00")


def test_resolve_gst_rate_percent_rejects_absurd_inference() -> None:
    data = InvoiceData(subtotal=Decimal("1"), gst=Decimal("50000"))
    assert resolve_gst_rate_percent(data) is None


def test_expected_gst_amount() -> None:
    assert expected_gst_amount(Decimal("1000"), Decimal("10")) == Decimal("100.00")
    assert expected_gst_amount(Decimal("1000"), Decimal("15")) == Decimal("150.00")


def test_invoice_gst_rate_fraction() -> None:
    data = InvoiceData(gst_rate=Decimal("10"))
    assert invoice_gst_rate_fraction(data) == 0.1
