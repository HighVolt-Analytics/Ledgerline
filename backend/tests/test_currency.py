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


def test_normalize_currency_rejects_greedy_substring_false_positives() -> None:
    """Never invent ISO from prose substrings (ARS in DOLLARS, EUR in EUROPEAN)."""
    assert normalize_currency("EUROPEAN") is None
    assert normalize_currency("US Dollars") is None
    assert normalize_currency("STANDARD") is None
    assert normalize_currency("AUD 100.00") == "AUD"
    assert normalize_currency("USD$") == "USD"
    assert normalize_currency("$100 AUD") == "AUD"
    assert normalize_currency("S$ 12.00") == "SGD"


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


def test_rm_inside_terms_is_not_myr() -> None:
    """Regression: 'RM' substring inside TERMS must not become MYR."""
    text = "Payment STANDARD terms Total 50.00\nFOR ALL ITEMS.\n"
    assert detect_currency_code_in_text(text) is None
    iso, symbol = resolve_currency_from_ocr(text)
    assert iso == ""
    assert symbol is None


def test_rm_near_amount_is_myr() -> None:
    assert detect_currency_code_in_text("Total RM 250.00") == "MYR"


def test_currency_label_resolves_iso() -> None:
    text = "Currency: USD\nTotal: 100.00"
    assert detect_currency_code_in_text(text) == "USD"


def test_detect_currency_ignores_for_all_items_false_positive() -> None:
    text = (
        "TOTAL AMOUNT PAYABLE : S$ 0.00\n"
        "FOR ALL ITEMS.\n"
        "PERMIT IS NOT REQUIRED.\n"
    )
    assert detect_currency_code_in_text(text) == "SGD"
    iso, symbol = resolve_currency_from_ocr(text)
    assert iso == "SGD"
    assert symbol is None


def test_detect_currency_sg_dollar_prefix() -> None:
    assert detect_currency_code_in_text("Total S$ 1,234.56") == "SGD"


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


def test_currency_evidence_accepts_prefix_and_glyph() -> None:
    from app.services.shared.currency import currency_evidence_in_text

    assert currency_evidence_in_text("SGD", "Total S$ 12.00")
    assert currency_evidence_in_text("USD", "Total US$37.08")
    assert currency_evidence_in_text("EUR", "Total €45.00")
    assert not currency_evidence_in_text("AUD", "Total $100.00 ABN 51824753556")
    assert currency_evidence_in_text("AUD", "Total AUD 100.00")


def test_amd_brand_on_invoice_is_not_armenian_dram() -> None:
    """Spectra-style tech invoices list AMD processors — never treat as currency."""
    from app.services.shared.currency import currency_evidence_in_text

    ocr = (
        "COMMERCIAL INVOICE\n"
        "Spectra Innovations Pte Ltd\n"
        "1 AMD Ryzen 5 5500 Desktop Processor 10 53.00 530.00\n"
        "2 AMD Ryzen 7 5700G Desktop Processor 30 145.00 4,350.00\n"
        "PAYMENT: SIGHT L/C\n"
        "Total 34,410.95\n"
    )
    assert detect_currency_code_in_text(ocr) is None
    assert not currency_evidence_in_text("AMD", ocr)
    iso, symbol = resolve_currency_from_ocr(ocr)
    assert iso == ""
    assert symbol is None


def test_amd_accepted_only_with_currency_anchor() -> None:
    from app.services.shared.currency import currency_evidence_in_text

    labeled = "Currency: AMD\nTotal: 100.00"
    assert detect_currency_code_in_text(labeled) == "AMD"
    assert currency_evidence_in_text("AMD", labeled)

    total_anchored = "Grand Total AMD 34,410.95"
    assert detect_currency_code_in_text(total_anchored) == "AMD"
    assert currency_evidence_in_text("AMD", total_anchored)

    # Bare adjacency without a totals/currency label is not enough.
    assert detect_currency_code_in_text("AMD 34,410.95") is None
    assert not currency_evidence_in_text("AMD", "AMD 34,410.95")


def test_bare_iso_token_is_not_currency_evidence() -> None:
    """Word-bounded ISO anywhere in the doc must not corroborate invented currency."""
    from app.services.shared.currency import currency_evidence_in_text

    ocr = "Vendor: USD Logistics Ltd\nTotal: 100.00\nFOR ALL ITEMS.\n"
    assert not currency_evidence_in_text("USD", ocr)
    assert detect_currency_code_in_text(ocr) is None


def test_normalize_currency_rejects_english_false_positive_iso() -> None:
    assert normalize_currency("ALL") is None
    assert normalize_currency("TRY") is None
    assert normalize_currency("USD") == "USD"