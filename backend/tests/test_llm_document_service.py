"""Tests for LLM document result schema validation."""

from __future__ import annotations

import pytest
from decimal import Decimal
from pydantic import ValidationError

from app.schemas.llm_document import LlmDocumentResult


def test_llm_result_accepts_valid_payload() -> None:
    result = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "dt-03",
            "confidence": 0.88,
            "reasoning": "Tax invoice with vendor and total",
            "perspective": "purchase",
        }
    )
    assert result.suggested_dt == "DT-03"
    assert result.confidence == pytest.approx(0.88)
    assert result.perspective == "purchase"


def test_llm_result_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        LlmDocumentResult.model_validate({"suggested_dt": "DT-03", "confidence": 1.5})


def test_llm_result_normalizes_unknown_perspective() -> None:
    result = LlmDocumentResult.model_validate(
        {"suggested_dt": "DT-16", "confidence": 0.5, "perspective": "maybe"}
    )
    assert result.perspective == "unknown"


def test_llm_result_coerces_empty_decimal_strings() -> None:
    result = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-03",
            "confidence": 0.8,
            "subtotal": "",
            "line_items": [{"description": "Widget", "unit_price": "", "amount": "10"}],
        }
    )
    assert result.subtotal is None
    assert result.line_items[0].unit_price is None
    assert result.line_items[0].amount == Decimal("10")


def test_llm_result_coerces_vendor_object() -> None:
    result = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-03",
            "confidence": 0.8,
            "vendor": {"name": "SPECTRA INNOVATIONS", "abn": "199904042N"},
        }
    )
    assert result.vendor == "SPECTRA INNOVATIONS"
