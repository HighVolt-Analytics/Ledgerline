"""OCR quality signal tests."""

from __future__ import annotations

from app.services.extraction.ocr_quality_signals import document_handwriting_likely


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
