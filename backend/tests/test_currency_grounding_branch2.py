"""Branch 2: contextual currency grounding and empty-currency hardening."""

from __future__ import annotations

from decimal import Decimal

from app.services.extraction.extraction_field_values import merge_gap_fill_into_parsed
from app.services.extraction.field_grounding_service import ground_invoice_scalars
from app.services.extraction.pdf_parser import _merge_prefer_complete
from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.validator import vr07_currency
from app.services.shared.currency import UNKNOWN_CURRENCY, convert_to_base, sum_amounts_by_currency

# Valid ABN checksum used across the test suite.
_ABN = "51824753556"


def test_ground_keeps_aud_via_tax_id_when_ocr_has_only_dollar() -> None:
    ocr = (
        f"TAX INVOICE\nABN {_ABN}\nVendor: Acme Pty Ltd\n"
        "Subtotal: $100.00\nGST 10%: $10.00\nTotal: $110.00\n"
    )
    parsed = InvoiceData(
        abn=_ABN,
        currency="AUD",
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        total=Decimal("110.00"),
        document_text=ocr,
    )
    grounded = ground_invoice_scalars(parsed, ocr)
    assert grounded.currency == "AUD"
    debug = (grounded.raw_fields or {}).get("_grounding_debug") or {}
    assert debug.get("currency") == "tax_id_context"


def test_ground_clears_currency_without_tax_id_or_iso() -> None:
    ocr = "Vendor: Acme Pty Ltd\nTotal: $100.00\n"
    parsed = InvoiceData(currency="AUD", total=Decimal("100.00"), document_text=ocr)
    grounded = ground_invoice_scalars(parsed, ocr)
    assert (grounded.currency or "") == ""


def test_ground_rejects_usd_when_abn_implies_aud() -> None:
    ocr = f"TAX INVOICE\nABN {_ABN}\nTotal: $100.00\n"
    parsed = InvoiceData(abn=_ABN, currency="USD", total=Decimal("100.00"), document_text=ocr)
    grounded = ground_invoice_scalars(parsed, ocr)
    assert (grounded.currency or "") == ""


def test_merge_prefer_complete_does_not_invent_sgd() -> None:
    primary = InvoiceData(currency="")
    secondary = InvoiceData(currency="")
    merged = _merge_prefer_complete(primary, secondary)
    assert (merged.currency or "") == ""


def test_gap_fill_still_rejects_currency_without_evidence() -> None:
    ocr_text = "Vendor: Acme Pty Ltd\nTotal: 100.00"
    parsed = InvoiceData(document_text=ocr_text, currency="")
    gap = InvoiceData(currency="AUD", document_text=ocr_text)
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["currency"],
        ocr_text=ocr_text,
    )
    assert not (result.parsed.currency or "").strip()
    assert result.rejected == ("currency",)


def test_gap_fill_accepts_aud_with_grounded_abn_on_parsed() -> None:
    ocr_text = f"Vendor: Acme\nABN {_ABN}\nTotal: $50.00"
    parsed = InvoiceData(document_text=ocr_text, currency="", abn=_ABN)
    gap = InvoiceData(currency="AUD", document_text=ocr_text)
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["currency"],
        ocr_text=ocr_text,
    )
    assert result.parsed.currency == "AUD"
    assert "currency" in result.filled


def test_convert_to_base_empty_currency_is_zero() -> None:
    assert convert_to_base(Decimal("100"), None) == Decimal("0")
    assert convert_to_base(Decimal("100"), "") == Decimal("0")
    assert convert_to_base(Decimal("100"), "   ") == Decimal("0")


def test_sum_amounts_unknown_currency_excluded_from_base() -> None:
    total, by_currency = sum_amounts_by_currency(
        [
            ("AUD", Decimal("100")),
            ("", Decimal("50")),
            (None, Decimal("25")),
        ],
        base="AUD",
    )
    assert by_currency["AUD"] == Decimal("100")
    assert by_currency[UNKNOWN_CURRENCY] == Decimal("75")
    assert total == Decimal("100")


def test_vr07_fails_when_currency_missing() -> None:
    result = vr07_currency(InvoiceData(currency=""), expected_currency="SGD")
    assert not result.passed
    assert "missing" in result.message.lower()
