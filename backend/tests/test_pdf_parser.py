"""Tests for PDF parsing (local heuristics and DI fallback)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.services.invoice_data import InvoiceData
from app.services.pdf_parser import (
    count_present_fields,
    local_parse_confident,
    parse_invoice,
    parse_local_text,
    parse_text_fields,
    should_use_document_intelligence,
)


SAMPLE_TEXT = """
Acme Cloud Pty Ltd
ABN: 53 004 085 616

Tax Invoice
Invoice No: AWS-AU-204815
Invoice Date: 15/03/2026
Due Date: 14/04/2026

Sub Total: $2,573.64
GST: $257.36
Invoice Total: $2,831.00
"""


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_parse_text_fields_extracts_core_fields() -> None:
    fields = parse_text_fields(SAMPLE_TEXT)
    assert fields["abn"] == "53004085616"
    assert fields["invoice_no"] == "AWS-AU-204815"
    assert fields["invoice_date"] == date(2026, 3, 15)
    assert fields["subtotal"] == Decimal("2573.64")
    assert fields["gst"] == Decimal("257.36")
    assert fields["total"] == Decimal("2831.00")


def test_local_parse_confident_when_complete() -> None:
    data = parse_local_text(SAMPLE_TEXT)
    assert local_parse_confident(data)
    assert count_present_fields(data) == 7


def test_local_parse_not_confident_when_missing_fields() -> None:
    data = parse_local_text("Hello world only")
    assert not local_parse_confident(data)


def test_should_use_di_when_text_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://test.cognitiveservices.azure.com")
    monkeypatch.setenv("AZURE_DI_KEY", "fake-key")
    get_settings.cache_clear()

    local = InvoiceData()
    assert should_use_document_intelligence("short", local)


def test_parse_invoice_local_only_without_di(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PARSE_MIN_TEXT_CHARS", "50")
    get_settings.cache_clear()

    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    def fake_extract(path: Path) -> str:
        return SAMPLE_TEXT

    monkeypatch.setattr(
        "app.services.pdf_parser.extract_pdf_text",
        fake_extract,
    )

    result = parse_invoice(pdf_path)
    assert result.source == "local"
    assert result.data.invoice_no == "AWS-AU-204815"
    assert local_parse_confident(result.data)


def test_parse_invoice_uses_di_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://test.cognitiveservices.azure.com")
    monkeypatch.setenv("AZURE_DI_KEY", "fake-key")
    get_settings.cache_clear()

    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.pdf_parser.extract_pdf_text",
        lambda _path: "",
    )

    di_data = InvoiceData(
        vendor="Azure Vendor Pty Ltd",
        abn="51824753556",
        invoice_no="DI-9001",
        invoice_date=date(2026, 1, 1),
        due_date=date(2026, 2, 1),
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
    )

    monkeypatch.setattr(
        "app.services.pdf_parser.parse_with_document_intelligence",
        lambda _path: di_data,
    )

    result = parse_invoice(pdf_path)
    assert result.source == "azure_di"
    assert result.data.invoice_no == "DI-9001"
    assert result.data.vendor == "Azure Vendor Pty Ltd"
