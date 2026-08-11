"""Tests for Field Translation Agent (llm.field_translate.system)."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.extraction.field_translation_service import (
    apply_field_translation,
    apply_field_translation_to_vision_header,
    apply_translation_detection_to_parsed,
    apply_translation_detection_to_vision_header,
    collect_translation_candidates,
    parse_translation_result,
    translation_needed,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
from app.services.prompt_registry.catalog import get_prompt_definition


def test_field_translate_prompt_registered() -> None:
    defn = get_prompt_definition("llm.field_translate.system")
    assert defn is not None
    assert "Field Translation Agent" in defn.default_body
    assert "source_language" in defn.default_body


def test_collect_candidates_skips_identity_and_vendor() -> None:
    fields, lines = collect_translation_candidates(
        document_heading="Rechnung",
        line_items=[ParsedLineItem(description="Bürostuhl Modell X")],
        extracted_fields={
            "vendor": "Müller GmbH",
            "seller_name": "Müller GmbH",
            "invoice_no": "RE-1",
            "statement_period": "Januar 2026",
            "original_document_heading": "stale",
        },
    )
    assert fields["document_heading"] == "Rechnung"
    assert fields["statement_period"] == "Januar 2026"
    assert "vendor" not in fields
    assert "seller_name" not in fields
    assert "invoice_no" not in fields
    assert "original_document_heading" not in fields
    assert lines == ["Bürostuhl Modell X"]


def test_translation_needed_false_when_empty() -> None:
    assert not translation_needed(
        document_heading="",
        line_items=[ParsedLineItem(description="")],
        extracted_fields={"invoice_no": "INV-1"},
    )


def test_parse_skips_already_english() -> None:
    result = parse_translation_result(
        {
            "source_language": "en",
            "confidence": 0.99,
            "fields": {"document_heading": "Invoice"},
            "line_descriptions": ["Chair"],
            "skip_reason": "already_english",
        },
        input_fields={"document_heading": "Invoice"},
        input_lines=["Chair"],
    )
    assert result["applied"] is False
    assert result["fields"] == {}
    assert result["line_descriptions"] == []


def test_parse_skips_low_confidence() -> None:
    result = parse_translation_result(
        {
            "source_language": "de",
            "confidence": 0.5,
            "fields": {"document_heading": "Invoice"},
            "line_descriptions": ["Office chair"],
            "skip_reason": "",
        },
        input_fields={"document_heading": "Rechnung"},
        input_lines=["Bürostuhl"],
    )
    assert result["applied"] is False
    assert "confidence" in (result["skip_reason"] or "")


def test_burmese_heading_is_translation_candidate() -> None:
    heading = "သင်္ဘော ပိုးကည်တိုက်"
    fields, _lines = collect_translation_candidates(
        document_heading=heading,
        line_items=[],
        extracted_fields={},
    )
    assert fields.get("document_heading") == heading
    assert translation_needed(document_heading=heading, line_items=[], extracted_fields={})


def test_parse_rejects_already_english_when_burmese_present() -> None:
    heading = "သင်္ဘော ပိုးကည်တိုက်"
    result = parse_translation_result(
        {
            "source_language": "en",
            "confidence": 0.99,
            "fields": {},
            "line_descriptions": [],
            "skip_reason": "already_english",
        },
        input_fields={"document_heading": heading},
        input_lines=[],
    )
    # Must not stick on already_english — caller may retry / model should translate.
    assert result["skip_reason"] != "already_english" or result["applied"] is False
    assert result["source_language"] not in {"en", "eng"}


def test_parse_applies_burmese_at_non_latin_confidence_floor() -> None:
    heading = "သင်္ဘော ပိုးကည်တိုက်"
    result = parse_translation_result(
        {
            "source_language": "my",
            "confidence": 0.78,
            "fields": {"document_heading": "Ship silk shop"},
            "line_descriptions": [],
            "skip_reason": "",
        },
        input_fields={"document_heading": heading},
        input_lines=[],
    )
    assert result["applied"] is True
    assert result["fields"]["document_heading"] == "Ship silk shop"


def test_apply_burmese_heading_stores_original() -> None:
    heading = "သင်္ဘော ပိုးကည်တိုက်"
    parsed = InvoiceData(document_heading=heading, extracted_fields={})
    updated = apply_translation_detection_to_parsed(
        parsed,
        {
            "source_language": "my",
            "confidence": 0.92,
            "fields": {"document_heading": "Boat silk shop"},
            "line_descriptions": [],
            "skip_reason": "",
            "applied": True,
            "raw": {},
        },
    )
    assert updated.document_heading == "Boat silk shop"
    assert updated.extracted_fields["original_document_heading"] == heading
    assert updated.extracted_fields["translation_applied"] == "true"
    assert updated.extracted_fields["translation_source_language"] == "my"


def test_apply_german_heading_and_lines_stores_originals() -> None:
    parsed = InvoiceData(
        vendor="Müller GmbH",
        invoice_no="RE-2026-1842",
        document_heading="Rechnung",
        total=Decimal("1234.56"),
        currency="EUR",
        line_items=[ParsedLineItem(description="Bürostuhl Modell X")],
        extracted_fields={"statement_period": "Januar 2026"},
    )
    detection = {
        "source_language": "de",
        "confidence": 0.95,
        "fields": {
            "document_heading": "Invoice",
            "statement_period": "January 2026",
        },
        "line_descriptions": ["Office chair Model X"],
        "skip_reason": "",
        "applied": True,
        "raw": {},
    }
    updated = apply_translation_detection_to_parsed(parsed, detection)
    assert updated.document_heading == "Invoice"
    assert updated.vendor == "Müller GmbH"
    assert updated.invoice_no == "RE-2026-1842"
    assert updated.total == Decimal("1234.56")
    assert updated.line_items[0].description == "Office chair Model X"
    assert updated.extracted_fields["original_document_heading"] == "Rechnung"
    assert updated.extracted_fields["original_statement_period"] == "Januar 2026"
    assert updated.extracted_fields["statement_period"] == "January 2026"
    assert updated.extracted_fields["translation_applied"] == "true"
    originals = json.loads(updated.extracted_fields["line_item_description_originals"])
    assert originals == ["Bürostuhl Modell X"]


def test_apply_noop_when_not_applied() -> None:
    parsed = InvoiceData(document_heading="Rechnung")
    updated = apply_translation_detection_to_parsed(
        parsed,
        {
            "source_language": "de",
            "confidence": 0.4,
            "fields": {},
            "line_descriptions": [],
            "skip_reason": "confidence_below_threshold",
            "applied": False,
            "raw": {},
        },
    )
    assert updated.document_heading == "Rechnung"
    assert updated.extracted_fields["translation_applied"] == "false"


def test_vision_header_helper_translates_before_persist_shape() -> None:
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="Rechnung",
        counterparty_name="Müller GmbH",
        invoice_no="RE-1",
        total=Decimal("10.00"),
        line_items=(ParsedLineItem(description="Bürostuhl"),),
        confidence=0.9,
    )
    detection = {
        "source_language": "de",
        "confidence": 0.92,
        "fields": {"document_heading": "Invoice"},
        "line_descriptions": ["Office chair"],
        "skip_reason": "",
        "applied": True,
        "raw": {},
    }
    updated, patch = apply_translation_detection_to_vision_header(result, detection)
    assert updated.document_heading == "Invoice"
    assert updated.counterparty_name == "Müller GmbH"
    assert updated.invoice_no == "RE-1"
    assert updated.line_items[0].description == "Office chair"
    assert patch["original_document_heading"] == "Rechnung"
    assert patch["translation_applied"] == "true"
    originals = json.loads(patch["line_item_description_originals"])
    assert originals == ["Bürostuhl"]


@pytest.mark.asyncio
async def test_apply_field_translation_english_no_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_TRANSLATE_EXTRACTED_FIELDS", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    parsed = InvoiceData(
        document_heading="Tax Invoice",
        line_items=[ParsedLineItem(description="Office chair")],
    )
    raw = {
        "source_language": "en",
        "confidence": 0.99,
        "fields": {},
        "line_descriptions": [],
        "skip_reason": "already_english",
    }
    with patch(
        "app.services.extraction.field_translation_service.chat_json_async",
        new_callable=AsyncMock,
        return_value=raw,
    ), patch(
        "app.services.extraction.field_translation_service.get_settings",
        return_value=type(
            "S",
            (),
            {
                "auto_translate_extracted_fields": True,
                "runtime_llm_available": True,
            },
        )(),
    ), patch(
        "app.services.extraction.field_translation_service.resolve_system_prompt_text",
        return_value="system",
    ):
        updated, detail = await apply_field_translation(
            parsed,
            context_text="Tax Invoice\nOffice chair",
            path="not_understood",
        )
    assert updated.document_heading == "Tax Invoice"
    assert updated.line_items[0].description == "Office chair"
    assert detail["field_translation_attempted"] is True
    assert detail["field_translation_applied"] is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_apply_field_translation_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch(
        "app.services.extraction.field_translation_service.get_settings",
        return_value=type(
            "S",
            (),
            {
                "auto_translate_extracted_fields": False,
                "runtime_llm_available": True,
            },
        )(),
    ):
        updated, detail = await apply_field_translation(
            InvoiceData(document_heading="Rechnung"),
            context_text="Rechnung",
        )
    assert updated.document_heading == "Rechnung"
    assert detail["skip_reason"] == "disabled"


@pytest.mark.asyncio
async def test_vision_path_apply_uses_agent() -> None:
    result = VisionHeaderExtractResult(
        success=True,
        document_heading="Factura",
        line_items=(ParsedLineItem(description="Silla"),),
        confidence=0.9,
    )
    raw = {
        "source_language": "es",
        "confidence": 0.93,
        "fields": {"document_heading": "Invoice"},
        "line_descriptions": ["Chair"],
        "skip_reason": "",
    }
    with patch(
        "app.services.extraction.field_translation_service.chat_json_async",
        new_callable=AsyncMock,
        return_value=raw,
    ), patch(
        "app.services.extraction.field_translation_service.get_settings",
        return_value=type(
            "S",
            (),
            {
                "auto_translate_extracted_fields": True,
                "runtime_llm_available": True,
            },
        )(),
    ), patch(
        "app.services.extraction.field_translation_service.resolve_system_prompt_text",
        return_value="system",
    ):
        updated, detail, patch_map = await apply_field_translation_to_vision_header(
            result,
            context_text="Factura\nSilla",
        )
    assert updated.document_heading == "Invoice"
    assert updated.line_items[0].description == "Chair"
    assert detail["path"] == "understood"
    assert detail["field_translation_applied"] is True
    assert patch_map["original_document_heading"] == "Factura"


def test_line_originals_length_matches_lines() -> None:
    parsed = InvoiceData(
        document_heading="Rechnung",
        line_items=[
            ParsedLineItem(description="Eins"),
            ParsedLineItem(description="Zwei"),
        ],
    )
    detection = {
        "source_language": "de",
        "confidence": 0.9,
        "fields": {"document_heading": "Invoice"},
        "line_descriptions": ["One", "Two"],
        "skip_reason": "",
        "applied": True,
        "raw": {},
    }
    updated = apply_translation_detection_to_parsed(parsed, detection)
    originals = json.loads(updated.extracted_fields["line_item_description_originals"])
    assert len(originals) == 2
    assert originals == ["Eins", "Zwei"]
