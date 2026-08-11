"""OCR quality signal tests."""

from __future__ import annotations

from app.services.extraction.ocr_quality_signals import (
    document_handwriting_likely,
    ocr_text_looks_corrupted,
    vendor_name_looks_ocr_garbage,
)
from app.services.invoice.vision_header_reconcile import text_usable_for_header_grounding
from app.services.master_data.vendor_name_utils import is_plausible_vendor_name


def test_handwriting_likely_on_high_variance() -> None:
    payload = {
        "ocr_words": [
            {"confidence": 0.3},
            {"confidence": 0.9},
            {"confidence": 0.2},
            {"confidence": 0.85},
            {"confidence": 0.4},
        ]
    }
    assert document_handwriting_likely(payload) is True


def test_handwriting_unlikely_on_uniform_high_confidence() -> None:
    payload = {"ocr_words": [{"confidence": 0.95} for _ in range(6)]}
    assert document_handwriting_likely(payload) is False


def test_clean_latin_invoice_text_not_corrupted() -> None:
    text = (
        "TAX INVOICE\nAcme Pty Ltd\nABN 51824753556\n"
        "Invoice No INV-100\nTotal AUD 1,234.56\n"
        "Thank you for your business.\n"
    )
    assert ocr_text_looks_corrupted(text) is False
    assert text_usable_for_header_grounding(text) is True


def test_misread_script_ocr_flagged_corrupted() -> None:
    # Generic OCR failure pattern: substantial Greek misread + Latin place names.
    text = (
        "εβδομάδα) - Junction City - ετσιμας(φως)ιστούς ληξηδιο διατροφηφοράζει\n"
        "Emgch Junction Center Tel 09 899 994 402\n"
        "2802 5.5.2026\n1 58000\nPaid Signature 58000Ks\n"
        "ποιοσιμος στημεφιστοριονέστουρ φραφίδι Bojko\n"
    )
    assert ocr_text_looks_corrupted(text) is True
    assert text_usable_for_header_grounding(text) is False


def test_vendor_garbage_rejected() -> None:
    garbage = "εβδομάδα) - Junction City - ετσιμας(φως)ιστούς ληξηδιο"
    assert vendor_name_looks_ocr_garbage(garbage) is True
    assert is_plausible_vendor_name(garbage) is False
    assert is_plausible_vendor_name("Atlassian Pty Ltd") is True
