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
from app.services.vendor_name_utils import is_plausible_vendor_name, pick_best_vendor_name


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


PO_TEXT = """
PURCHASE ORDER
Sysco Foods Australia Pty Ltd
ABN 51 824 753 556
Purchase Order Number: PO-MKT-2026-TEST
PO Date: 09 June 2026
Description Qty Unit Price Amount
Fresh produce delivery 10 50.00 500.00
Subtotal AUD 500.00
GST 10% 0.00
TOTAL AUD 500.00
"""

GRN_TEXT = """
GOODS RECEIPT NOTE
Sysco Foods Australia Pty Ltd
GRN Number: GRN-PO-MKT-2026-TEST
PO Reference: PO-MKT-2026-TEST
Receipt Date: 10 June 2026
Description Qty Received Condition
Fresh produce delivery 10 Good
"""


def test_parse_po_document_fields() -> None:
    fields = parse_text_fields(PO_TEXT)
    assert fields["vendor"] == "Sysco Foods Australia Pty Ltd"
    assert fields["po_reference"] == "PO-MKT-2026-TEST"
    assert fields["abn"] == "51824753556"
    assert fields["gst"] == Decimal("0.00")
    assert fields["subtotal"] == Decimal("500.00")
    assert fields["total"] == Decimal("500.00")
    assert fields["invoice_date"] == date(2026, 6, 9)
    assert len(fields["line_items"]) == 1
    assert fields["line_items"][0].description == "Fresh produce delivery"


def test_parse_grn_document_fields() -> None:
    fields = parse_text_fields(GRN_TEXT)
    assert fields["vendor"] == "Sysco Foods Australia Pty Ltd"
    assert fields["po_reference"] == "PO-MKT-2026-TEST"
    assert fields["invoice_date"] == date(2026, 6, 10)
    assert len(fields["line_items"]) == 1
    assert fields["line_items"][0].qty == Decimal("10")


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


AZURE_INVOICE_TEXT = """
Microsoft Azure TAX INVOICE
1 Epping Road, North Ryde NSW 2113
ABN: 31 002 882 614
BILL TO Invoice No MSFT-AZ-AU-77192
Highvolt Pty Ltd Invoice Date 2026-05-18
Sydney NSW, Australia Due Date 2026-06-17
ABN: 99 888 777 666
Currency AUD
Cost Centre ENG-PLATFORM
DESCRIPTION QTY UNIT PRICE GST AMOUNT
Azure Cloud Compute - May 2026 1 $1,820.00 $182.00 $2,002.00
Azure Blob Storage - May 2026 1 $260.00 $26.00 $286.00
Subtotal $2,080.00
GST (10%) $208.00
Total Due $2,288.00
Payment Terms: Net 30 days from invoice date. Please reference the invoice number with payment. GST is charged at the prevailing
Australian rate of 10%.
"""


def test_parse_azure_invoice_vendor_from_header() -> None:
    fields = parse_text_fields(AZURE_INVOICE_TEXT)
    assert fields["vendor"] == "Microsoft Azure"
    assert fields["abn"] == "31002882614"


def test_rejects_payment_footer_as_vendor_name() -> None:
    footer = (
        "invoice date. Please reference the invoice number with payment. "
        "GST is charged at the prevailing Australian rate of 10%."
    )
    assert not is_plausible_vendor_name(footer)


def test_pick_best_vendor_prefers_plausible_local_over_di_footer() -> None:
    di_footer = (
        "invoice date. Please reference the invoice number with payment. "
        "GST is charged a"
    )
    assert pick_best_vendor_name(di_footer, "Microsoft Azure") == "Microsoft Azure"


def test_parse_azure_invoice_merges_sane_vendor_over_di_footer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://test.cognitiveservices.azure.com")
    monkeypatch.setenv("AZURE_DI_KEY", "fake-key")
    get_settings.cache_clear()

    pdf_path = tmp_path / "azure.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.pdf_parser.extract_pdf_text",
        lambda _path: AZURE_INVOICE_TEXT,
    )

    di_data = InvoiceData(
        vendor=(
            "invoice date. Please reference the invoice number with payment. "
            "GST is charged a"
        ),
        abn="31002882614",
        invoice_no="MSFT-AZ-AU-77192",
        invoice_date=date(2026, 5, 18),
        subtotal=Decimal("2080.00"),
        gst=Decimal("208.00"),
        total=Decimal("2288.00"),
    )
    monkeypatch.setattr(
        "app.services.pdf_parser.parse_with_document_intelligence",
        lambda _path: di_data,
    )

    result = parse_invoice(pdf_path)
    assert result.data.vendor == "Microsoft Azure"
