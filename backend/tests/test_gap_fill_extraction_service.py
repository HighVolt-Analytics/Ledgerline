"""Tests for AI OCR gap-fill extraction service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_field_values import (
    merge_gap_fill_into_parsed,
    missing_configured_extraction_keys,
)
from app.services.extraction.gap_fill_extraction_service import (
    apply_extraction_gap_fill,
    build_gap_fill_system_prompt,
    build_gap_fill_user_payload,
    gap_fill_missing_fields,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.tenant.tenant_org_context import OrgContext


def test_build_gap_fill_system_prompt_includes_accuracy_contract() -> None:
    prompt = build_gap_fill_system_prompt(missing_keys=["account_code", "project_code"])
    assert "missing_fields" in prompt.lower() or "ONLY the missing_fields" in prompt
    assert "verbatim" in prompt.lower()
    assert "account_code" in prompt or "extracted_fields" in prompt
    assert "Do NOT guess" in prompt or "do not guess" in prompt.lower()


def test_build_gap_fill_user_payload_includes_snippets() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Vendor: Acme Pty Ltd\nAccount Code: 4100\nTotal: 100.00",
        text_length=50,
    )
    payload = build_gap_fill_user_payload(ocr=ocr, missing_keys=["account_code"])
    import json

    data = json.loads(payload)
    assert data["missing_fields"] == ["account_code"]
    assert "4100" in data["field_snippets"]["account_code"]
    assert "Account Code" in data["field_snippets"]["account_code"]


def test_missing_configured_extraction_keys_skips_present() -> None:
    parsed = InvoiceData(vendor="Acme", document_text="Vendor: Acme")
    missing = missing_configured_extraction_keys(
        ["vendor", "account_code"],
        parsed=parsed,
    )
    assert missing == ["account_code"]


def test_merge_gap_fill_does_not_overwrite_existing_vendor() -> None:
    ocr_text = "Vendor: Acme Pty Ltd\nVendor: Other Co"
    parsed = InvoiceData(vendor="Acme Pty Ltd", document_text=ocr_text)
    gap = InvoiceData(vendor="Other Co", document_text=ocr_text)
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["vendor", "account_code"],
        ocr_text=ocr_text,
    )
    assert result.parsed.vendor == "Acme Pty Ltd"
    assert "vendor" not in result.filled


def test_merge_gap_fill_fills_grounded_account_code() -> None:
    ocr_text = "Account Code: 4100\nVendor: Acme"
    parsed = InvoiceData(document_text=ocr_text)
    gap = InvoiceData(
        document_text=ocr_text,
        extracted_fields={"account_code": "4100"},
    )
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["account_code"],
        ocr_text=ocr_text,
    )
    assert result.parsed.extracted_fields.get("account_code") == "4100"
    assert result.filled == ("account_code",)
    assert result.rejected == ()


def test_merge_gap_fill_rejects_hallucinated_project_code() -> None:
    ocr_text = "Vendor: Acme Pty Ltd\nInvoice No: INV-1"
    parsed = InvoiceData(document_text=ocr_text)
    gap = InvoiceData(
        document_text=ocr_text,
        extracted_fields={"project_code": "PRJ-999"},
    )
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["project_code"],
        ocr_text=ocr_text,
    )
    assert "project_code" not in result.parsed.extracted_fields
    assert result.rejected == ("project_code",)


def test_merge_gap_fill_rejects_default_currency_without_ocr_anchor() -> None:
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


@pytest.mark.asyncio
async def test_gap_fill_missing_fields_mock_llm_fills_account_code() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Vendor: Acme\nAccount Code: 4100",
        text_length=30,
    )
    raw = {
        "extracted_fields": {"account_code": "4100"},
        "field_confidence": {"account_code": 0.95},
        "suggested_dt": "",
        "confidence": 0.9,
        "reasoning": "",
        "perspective": "purchase",
    }
    with patch(
        "app.services.extraction.gap_fill_extraction_service.chat_json_async",
        new_callable=AsyncMock,
        return_value=raw,
    ):
        gap = await gap_fill_missing_fields(
            ocr,
            missing_keys=["account_code"],
            org=OrgContext(),
        )
    assert gap is not None
    assert gap.extracted_fields.get("account_code") == "4100"


@pytest.mark.asyncio
async def test_apply_extraction_gap_fill_leaves_absent_field_empty() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Vendor: Acme Pty Ltd\nTotal: 50.00",
        text_length=30,
    )
    parsed = InvoiceData(vendor="Acme Pty Ltd", document_text=ocr.text)
    raw = {
        "extracted_fields": {"project_code": "PRJ-INVENTED"},
        "field_confidence": {"project_code": 0.95},
        "suggested_dt": "",
        "confidence": 0.9,
        "reasoning": "",
        "perspective": "purchase",
    }
    with patch(
        "app.services.extraction.gap_fill_extraction_service.chat_json_async",
        new_callable=AsyncMock,
        return_value=raw,
    ):
        updated, detail = await apply_extraction_gap_fill(
            parsed,
            ocr=ocr,
            selected_keys=["vendor", "project_code"],
            org=OrgContext(),
        )
    assert detail["gap_fill_attempted"] is True
    assert "project_code" in detail["gap_fill_rejected"]
    assert "project_code" not in updated.extracted_fields
