from decimal import Decimal

from app.services.extraction.field_validators import normalize_currency
from app.services.shared.currency import (
    UNKNOWN_CURRENCY,
    apply_currency_ocr_fallback,
    convert_to_base,
    detect_currency_code_in_text,
    detect_currency_symbol_in_text,
    resolve_currency_from_ocr,
    sum_amounts_by_currency,
)
from app.services.invoice.invoice_data import InvoiceData


def test_convert_to_base_usd() -> None:
    assert convert_to_base(Decimal("100"), "USD", base="AUD") == Decimal("155.00")


def test_sum_amounts_by_currency_mixed() -> None:
    total, by_currency = sum_amounts_by_currency(
        [
            ("AUD", Decimal("100")),
            ("USD", Decimal("100")),
        ],
        base="AUD",
    )
    assert by_currency["AUD"] == Decimal("100")
    assert by_currency["USD"] == Decimal("100")
    assert total == Decimal("255.00")


def test_convert_to_base_blank_currency_not_base() -> None:
    assert convert_to_base(Decimal("100"), None, base="SGD") == Decimal("0")
    assert convert_to_base(Decimal("100"), "", base="SGD") == Decimal("0")


def test_sum_amounts_blank_currency_unknown_bucket() -> None:
    total, by_currency = sum_amounts_by_currency(
        [
            ("SGD", Decimal("100")),
            ("", Decimal("40")),
            (None, Decimal("10")),
        ],
        base="SGD",
    )
    assert by_currency["SGD"] == Decimal("100")
    assert by_currency[UNKNOWN_CURRENCY] == Decimal("50")
    assert total == Decimal("100")


def test_normalize_currency_rejects_ambiguous_dollar() -> None:
    assert normalize_currency("$") is None
    assert normalize_currency("¥") is None
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("£") == "GBP"
    assert normalize_currency("₹") == "INR"
    assert normalize_currency("usd") == "USD"


def test_detect_currency_symbol_launchdarkly_style() -> None:
    text = (
        "Catamorphic Co DBA LaunchDarkly\n"
        "$156.00 paid on May 3, 2026\n"
        "Subtotal $156.00\n"
        "Total excluding tax $156.00\n"
    )
    assert detect_currency_code_in_text(text) is None
    assert detect_currency_symbol_in_text(text) == "$"
    iso, symbol = resolve_currency_from_ocr(text)
    assert iso == ""
    assert symbol == "$"


def test_detect_currency_iso_in_text() -> None:
    text = "Invoice total USD 99.00\nAmount due: USD 99.00"
    assert detect_currency_code_in_text(text) == "USD"
    iso, symbol = resolve_currency_from_ocr(text)
    assert iso == "USD"
    assert symbol is None


def test_detect_unlisted_iso_near_money() -> None:
    """Any ISO 4217 code near money resolves (catalog from pycountry, e.g. BRL)."""
    from app.services.shared.iso4217_catalog import is_iso4217_currency

    assert is_iso4217_currency("BRL")
    text = "Amount due BRL 250.00\nTotal BRL 250.00"
    assert detect_currency_code_in_text(text) == "BRL"


def test_ignore_non_iso_three_letter_tokens() -> None:
    from app.services.shared.iso4217_catalog import is_iso4217_currency

    assert not is_iso4217_currency("GST")
    assert not is_iso4217_currency("MAY")
    assert not is_iso4217_currency("DUE")
    text = "GST 10.00\nTAX 5.00\nABN 12 345 678 901\npaid on May 3, 2026"
    assert detect_currency_code_in_text(text) is None


def test_unambiguous_euro_symbol_maps_to_iso() -> None:
    text = "Total €45.00 due"
    iso, symbol = resolve_currency_from_ocr(text)
    assert iso == "EUR"
    assert symbol is None


def test_apply_currency_ocr_fallback_sets_symbol() -> None:
    parsed = InvoiceData(total=Decimal("156"), currency="")
    updated = apply_currency_ocr_fallback(
        parsed,
        "Service Connections\n1 $156.00 $156.00\nSubtotal $156.00",
    )
    assert updated.currency == ""
    assert (updated.extracted_fields or {}).get("currency_symbol") == "$"


def test_apply_currency_ocr_fallback_keeps_existing_iso() -> None:
    parsed = InvoiceData(currency="USD", total=Decimal("10"))
    updated = apply_currency_ocr_fallback(parsed, "Total $10.00")
    assert updated.currency == "USD"
    assert "currency_symbol" not in (updated.extracted_fields or {})
