"""Unit tests for vision header extract parse + persist."""

from __future__ import annotations

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services.extraction.document_ai_provider import DocumentAiProvider
from app.services.invoice.vision_header_extract import (
    evaluate_vision_header_extract,
    parse_vision_header_raw,
    persist_vision_header_to_invoice,
)
from app.services.tenant.tenant_org_context import OrgContext
from app.tenant_ids import TESTING_TENANT_UUID


def test_parse_vision_header_raw_success() -> None:
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "counterparty_name": "Acme Pty Ltd",
            "perspective": "purchase",
            "invoice_no": "INV-9",
            "proforma_invoice_no": "PI-1",
            "po_reference": "PO-1",
            "so_reference": "",
            "other_reference": "GRN-3",
            "invoice_date": "2026-03-15",
            "total": "1,234.56",
            "currency": "AUD",
            "confidence": 0.91,
            "reason": "clear",
        },
        provider="gemini_vision",
        page_count=2,
    )
    assert result.success is True
    assert result.document_heading == "TAX INVOICE"
    assert result.canonical_document_type == "Tax Invoice"
    assert result.counterparty_name == "Acme Pty Ltd"
    assert result.proforma_invoice_no == "PI-1"
    assert result.other_reference == "GRN-3"
    assert result.invoice_date.isoformat() == "2026-03-15"
    assert str(result.total) == "1234.56"
    assert result.currency == "AUD"
    assert result.page_count == 2


def test_parse_vision_header_aliases_and_currency_prefixed_total() -> None:
    result = parse_vision_header_raw(
        {
            "documentHeading": "SALES TAX INVOICE",
            "canonicalDocumentType": "Tax Invoice",
            "counterpartyName": "Acme Retail Pty Ltd",
            "perspective": "sales",
            "invoiceNo": "SI-TEST-9100",
            "soReference": "SO-TEST-2026-100",
            "invoiceDate": "15/03/2026",
            "grand_total": "AUD 2,500.00",
            "confidence": 0.88,
            "reason": "alias keys",
        },
        provider="gemini_vision",
    )
    assert result.success is True
    assert result.document_heading == "SALES TAX INVOICE"
    assert result.counterparty_name == "Acme Retail Pty Ltd"
    assert result.invoice_no == "SI-TEST-9100"
    assert result.so_reference == "SO-TEST-2026-100"
    assert result.invoice_date.isoformat() == "2026-03-15"
    assert str(result.total) == "2500.00"
    assert result.currency == "AUD"


def test_parse_vision_header_raw_empty() -> None:
    result = parse_vision_header_raw(None, provider="gemini_vision")
    assert result.success is False
    assert result.fail_reason == "provider_empty_response"


def test_persist_vision_header_clears_seeded_currency_when_empty() -> None:
    """Vision empty currency must not leave ingest/tenant AUD behind."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        extracted_fields={"currency": "AUD"},
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "counterparty_name": "Acme",
            "perspective": "purchase",
            "invoice_no": "INV-1",
            "po_reference": "",
            "so_reference": "",
            "other_reference": "",
            "invoice_date": "",
            "total": "100.00",
            "currency": "",
            "confidence": 0.9,
            "reason": "bare dollar ambiguous",
        },
        provider="gemini_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.currency == ""
    assert "currency" not in (inv.extracted_fields or {})


def test_persist_vision_header_date_total_currency() -> None:
    from datetime import date
    from decimal import Decimal

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "counterparty_name": "Acme Pty Ltd",
            "perspective": "purchase",
            "invoice_no": "INV-100",
            "po_reference": "",
            "so_reference": "",
            "other_reference": "",
            "invoice_date": "15/03/2026",
            "total": "$2,500.00",
            "currency": "AUD",
            "confidence": 0.9,
            "reason": "amounts present",
        },
        provider="gemini_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.invoice_date == date(2026, 3, 15)
    assert inv.total == Decimal("2500.00")
    assert inv.currency == "AUD"
    fields = inv.extracted_fields or {}
    assert fields.get("invoice_date") == "2026-03-15"
    assert fields.get("total") == "2500.00"
    assert fields.get("currency") == "AUD"


def test_persist_vision_header_canonical_type() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "G.R.N.",
            "canonical_document_type": "Goods Receipt Note",
            "counterparty_name": "Supplier Co",
            "perspective": "purchase",
            "invoice_no": "",
            "po_reference": "PO-777",
            "so_reference": "",
            "other_reference": "",
            "confidence": 0.8,
            "reason": "grn",
        },
        provider="azure_foundry_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.document_heading == "G.R.N."
    assert (inv.extracted_fields or {}).get("canonical_document_type") == "Goods Receipt Note"


def test_persist_vision_header_to_invoice_columns() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "Purchase Order",
            "counterparty_name": "Supplier Co",
            "perspective": "purchase",
            "invoice_no": "",
            "po_reference": "PO-777",
            "so_reference": "",
            "other_reference": "",
            "confidence": 0.8,
            "reason": "po header",
        },
        provider="azure_foundry_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.document_heading == "Purchase Order"
    assert inv.po_reference == "PO-777"
    assert inv.vendor == "Supplier Co"
    fields = inv.extracted_fields or {}
    assert fields.get("document_heading") == "Purchase Order"
    assert fields.get("seller_name") == "Supplier Co"


def test_persist_proforma_invoice_no_to_extracted_fields() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "PROFORMA INVOICE",
            "counterparty_name": "Acme",
            "perspective": "purchase",
            "invoice_no": "",
            "proforma_invoice_no": "PI-900",
            "po_reference": "",
            "so_reference": "",
            "other_reference": "",
            "confidence": 0.85,
            "reason": "proforma",
        },
        provider="gemini_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.invoice_no is None or inv.invoice_no == ""
    assert (inv.extracted_fields or {}).get("proforma_invoice_no") == "PI-900"


def test_persist_sales_counterparty_as_buyer() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "Sales Order",
            "counterparty_name": "Customer Ltd",
            "perspective": "sales",
            "invoice_no": "",
            "po_reference": "",
            "so_reference": "SO-12",
            "other_reference": "",
            "confidence": 0.7,
            "reason": "so",
        },
        provider="gemini_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.so_reference == "SO-12"
    assert inv.vendor == "Customer Ltd"
    assert (inv.extracted_fields or {}).get("buyer_name") == "Customer Ltd"


@pytest.mark.asyncio
async def test_evaluate_vision_header_fail_closed_azure_di(tmp_path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    result = await evaluate_vision_header_extract(
        pdf,
        provider=DocumentAiProvider.AZURE_DI,
        org=OrgContext(legal_name="Tenant Co"),
    )
    assert result.success is False
    assert result.fail_reason == "vision_provider_not_configured"


@pytest.mark.asyncio
async def test_evaluate_vision_header_provider_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.invoice.vision_header_extract.resolve_pdf_page_images",
        lambda *_a, **_k: [b"png"],
    )
    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.provider_available",
        lambda _p: True,
    )

    async def _boom(**_kwargs):
        raise TimeoutError("timeout")

    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.extract_vision_header",
        _boom,
    )

    result = await evaluate_vision_header_extract(
        pdf,
        provider=DocumentAiProvider.GEMINI_VISION,
        org=OrgContext(legal_name="Tenant Co"),
    )
    assert result.success is False
    assert result.fail_reason == "provider_error"
