"""Tests for AI OCR gap-fill extraction service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from decimal import Decimal

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
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
from app.services.extraction.llm_document_service import _normalize_llm_raw
from app.services.invoice.invoice_data import InvoiceData
from app.services.tenant.tenant_org_context import OrgContext


def test_normalize_llm_raw_coerces_scalar_field_confidence() -> None:
    normalized = _normalize_llm_raw(
        {"vendor": "Acme Pty Ltd", "field_confidence": 0.0},
        selected_keys=["vendor"],
    )
    assert normalized["field_confidence"] == {}
    assert normalized["vendor"] == "Acme Pty Ltd"


@pytest.mark.asyncio
async def test_gap_fill_missing_fields_accepts_scalar_field_confidence() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Vendor: Acme Pty Ltd\nAccount Code: 4100",
        text_length=40,
    )
    raw = {
        "vendor": "Acme Pty Ltd",
        "field_confidence": 0.0,
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
            missing_keys=["vendor"],
            org=OrgContext(),
        )
    assert gap is not None
    assert gap.vendor == "Acme Pty Ltd"


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


def test_missing_configured_extraction_keys_includes_line_items_for_qty_table() -> None:
    from pathlib import Path

    text = Path("tests/fixtures/qty_only_table_ocr.txt").read_text(encoding="utf-8")
    parsed = InvoiceData(document_text=text, line_items=[])
    missing = missing_configured_extraction_keys(
        ["line_items"],
        parsed=parsed,
        ocr_text=text,
        ocr_payload={},
    )
    assert missing == ["line_items"]


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


@pytest.mark.asyncio
async def test_gap_fill_recovers_vendor_when_di_ungrounded() -> None:
    ocr_text = "TAX INVOICE\nVendor: Real Co"
    ocr = OcrArtifact(
        success=True,
        text=ocr_text,
        text_length=len(ocr_text),
        payload_json={
            "invoice_fields": {"vendor": "Hallucinated Vendor"},
        },
    )
    parsed = InvoiceData(document_text=ocr_text)
    raw = {
        "vendor": "Real Co",
        "field_confidence": {"vendor": 0.95},
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
            missing_keys=["vendor"],
            org=OrgContext(),
        )
    assert gap is not None
    assert gap.vendor == "Real Co"
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["vendor"],
        ocr_text=ocr_text,
    )
    assert result.parsed.vendor == "Real Co"
    assert result.filled == ("vendor",)


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


SPECTRA_COMMERCIAL_OCR = """COMMERCIAL INVOICE
Invoice No.: 260671582
MODEL DESCRIPTION QTY UNIT PRICE AMOUNT
ST20000NM002H 3.5" INTERNAL HDD 20TB 80 499.00 39920.00
TOTAL 39,920.00"""


@pytest.mark.asyncio
async def test_gap_fill_line_items_spectra_commercial() -> None:
    ocr = OcrArtifact(
        success=True,
        text=SPECTRA_COMMERCIAL_OCR,
        text_length=len(SPECTRA_COMMERCIAL_OCR),
    )
    raw = {
        "line_items": [
            {
                "description": 'ST20000NM002H 3.5" INTERNAL HDD 20TB',
                "qty": 80,
                "unit_price": 499.00,
                "amount": 39920.00,
            }
        ],
        "field_confidence": 0.0,
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
            missing_keys=["line_items"],
            org=OrgContext(),
        )
    assert gap is not None
    assert len(gap.line_items) == 1
    assert gap.line_items[0].qty == Decimal("80")

    parsed = InvoiceData(
        vendor="Spectra Innovations Pte Ltd",
        document_text=SPECTRA_COMMERCIAL_OCR,
    )
    merged = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["line_items"],
        ocr_text=SPECTRA_COMMERCIAL_OCR,
    )
    assert len(merged.parsed.line_items) == 1
    assert merged.parsed.line_items[0].amount == Decimal("39920.00")


def test_gap_fill_spectra_line_items_pass_field_confidence_gate() -> None:
    from app.schemas.rule_book_config import AiClassificationConfig
    from app.services.invoice.invoice_data import ParsedLineItem
    from app.services.invoice.invoice_pipeline_phases import evaluate_field_confidence_gate

    llm = LlmDocumentResult(
        suggested_dt="DT-01",
        confidence=0.95,
        vendor="Spectra Innovations Pte Ltd",
        field_confidence={},
    )
    parsed = InvoiceData(
        vendor="Spectra Innovations Pte Ltd",
        total=Decimal("39920.00"),
        line_items=[
            ParsedLineItem(
                description='ST20000NM002H 3.5" INTERNAL HDD 20TB',
                qty=Decimal("80"),
                unit_price=Decimal("499.00"),
                amount=Decimal("39920.00"),
            )
        ],
        document_text=SPECTRA_COMMERCIAL_OCR,
    )
    invoice = Invoice(vendor="Spectra Innovations Pte Ltd")
    invoice.total = Decimal("39920.00")
    dt = DocumentTypeDefinition(
        code="DT-01",
        title="PO goods",
        shortTitle="Goods",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=[],
        llm_prompt="",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(),
        extractionFields=["vendor", "total", "line_items"],
        requiredFields=["vendor", "total", "line_items"],
    )
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
        dt_definition=dt,
        parsed=parsed,
        invoice=invoice,
        confirmed_dt="DT-01",
    )
    assert result.passed is True
    assert "line_items" not in result.missing_gate_fields


@pytest.mark.asyncio
async def test_chat_json_retries_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.extraction import azure_openai_client

    calls = {"count": 0}

    def _flaky_chat(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("The read operation timed out")
        return {"vendor": "Acme", "field_confidence": {"vendor": 0.95}}

    monkeypatch.setattr(azure_openai_client, "_chat_json_once", _flaky_chat)
    monkeypatch.setattr(azure_openai_client, "is_azure_openai_enabled", lambda: True)

    result = azure_openai_client.chat_json(system="s", user="u")
    assert result == {"vendor": "Acme", "field_confidence": {"vendor": 0.95}}
    assert calls["count"] == 2
