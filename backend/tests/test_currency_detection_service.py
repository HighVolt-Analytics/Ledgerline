"""Unit tests for Currency Detection Agent parsing / apply helpers."""

from __future__ import annotations

from app.services.extraction.currency_detection_service import (
    apply_currency_detection_to_parsed,
    parse_currency_detection_result,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.prompt_registry.catalog import get_prompt_definition


def test_currency_prompt_registered() -> None:
    defn = get_prompt_definition("llm.currency.system")
    assert defn is not None
    assert "Currency Detection Agent" in defn.default_body
    assert "HR1. NEVER assign a currency ISO code from a bare" in defn.default_body
    assert 'Prefer "UNCERTAIN" over a wrong answer' in defn.default_body


def test_parse_applies_high_confidence_iso() -> None:
    raw = {
        "document_currency": {
            "iso_code": "AUD",
            "symbol_seen": "$",
            "confidence": 0.98,
            "decision_basis": ["D4", "S3"],
            "evidence": [],
            "conflicts": [],
        },
        "amounts": [],
        "multi_currency_document": False,
        "secondary_currencies": [],
        "human_review_required": False,
        "review_reason": None,
        "critical_flags": [],
    }
    result = parse_currency_detection_result(raw)
    assert result["applied"] is True
    assert result["iso_code"] == "AUD"
    assert result["human_review_required"] is False


def test_parse_uncertain_does_not_apply() -> None:
    raw = {
        "document_currency": {
            "iso_code": "UNCERTAIN",
            "symbol_seen": "$",
            "confidence": 0.0,
            "decision_basis": ["D6"],
            "evidence": [],
            "conflicts": [],
        },
        "amounts": [],
        "multi_currency_document": False,
        "secondary_currencies": [],
        "human_review_required": True,
        "review_reason": "Bare ambiguous symbol with no corroborating jurisdiction signal",
        "critical_flags": ["AMBIGUOUS_SYMBOL_NO_CONTEXT"],
    }
    result = parse_currency_detection_result(raw)
    assert result["applied"] is False
    assert result["iso_code"] == ""
    assert result["human_review_required"] is True


def test_parse_low_confidence_does_not_apply() -> None:
    raw = {
        "document_currency": {
            "iso_code": "USD",
            "symbol_seen": "$",
            "confidence": 0.7,
            "decision_basis": ["D3"],
            "evidence": [],
            "conflicts": [],
        },
        "human_review_required": True,
        "review_reason": "Confidence below threshold",
        "critical_flags": [],
    }
    result = parse_currency_detection_result(raw)
    assert result["applied"] is False
    assert result["candidate_iso"] == "USD"
    assert result["iso_code"] == ""


def test_apply_sets_currency_and_audit() -> None:
    parsed = InvoiceData(currency="", document_text="Total S$ 10.00")
    detection = parse_currency_detection_result(
        {
            "document_currency": {
                "iso_code": "SGD",
                "symbol_seen": "S$",
                "confidence": 0.95,
                "decision_basis": ["D3"],
                "evidence": [{"signal_type": "symbol_form", "value": "S$", "location": "header", "weight": 0.85}],
                "conflicts": [],
            },
            "human_review_required": False,
            "review_reason": None,
            "critical_flags": [],
            "multi_currency_document": False,
        }
    )
    updated = apply_currency_detection_to_parsed(
        parsed,
        detection,
        ocr_text="Total S$ 10.00",
    )
    assert updated.currency == "SGD"
    assert (updated.raw_fields or {}).get("currency_detection", {}).get("applied") is True


def test_apply_rejects_ungrounded_jurisdiction_guess_leaves_bare_dollar_empty() -> None:
    """ABN + bare $ must not store invented AUD or USD — leave ISO empty, keep glyph."""
    ocr = "TAX INVOICE\nABN 51824753556\nTotal: $100.00"
    parsed = InvoiceData(currency="", document_text=ocr)
    detection = parse_currency_detection_result(
        {
            "document_currency": {
                "iso_code": "AUD",
                "symbol_seen": "$",
                "confidence": 0.95,
                "decision_basis": ["D4"],
                "evidence": [],
                "conflicts": [],
            },
            "human_review_required": False,
            "review_reason": None,
            "critical_flags": [],
            "multi_currency_document": False,
        }
    )
    updated = apply_currency_detection_to_parsed(parsed, detection, ocr_text=ocr)
    assert (updated.currency or "") == ""
    audit = (updated.raw_fields or {}).get("currency_detection") or {}
    assert audit.get("applied") is False
    assert audit.get("grounding_rejected") is True
    assert not audit.get("fallback_iso")
    assert (updated.extracted_fields or {}).get("currency_symbol") == "$"
