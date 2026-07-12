"""Tests for pycountry-backed ISO 4217 catalog."""

from app.services.extraction.locale_vocab import SUPPORTED_CURRENCY_CODES
from app.services.shared.iso4217_catalog import (
    currency_alternation_regex,
    is_iso4217_currency,
    iso4217_currency_codes,
)


def test_iso4217_catalog_includes_common_codes() -> None:
    codes = iso4217_currency_codes()
    assert len(codes) > 100
    for code in ("AUD", "USD", "EUR", "GBP", "SGD", "INR", "BRL", "JPY"):
        assert code in codes
        assert is_iso4217_currency(code)


def test_iso4217_rejects_non_currency_tokens() -> None:
    assert not is_iso4217_currency("GST")
    assert not is_iso4217_currency("MAY")
    assert not is_iso4217_currency("DUE")
    assert not is_iso4217_currency("")
    assert not is_iso4217_currency("US")


def test_locale_vocab_uses_iso4217_catalog() -> None:
    assert SUPPORTED_CURRENCY_CODES == iso4217_currency_codes()
    alt = currency_alternation_regex()
    assert "USD" in alt
    assert "BRL" in alt
