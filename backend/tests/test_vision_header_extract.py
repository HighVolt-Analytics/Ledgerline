"""Unit tests for vision header extract parse + persist."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services.extraction.document_ai_provider import DocumentAiProvider
from app.services.invoice.vision_header_extract import (
    VisionHeaderExtractResult,
    derive_canonical_document_type,
    evaluate_vision_header_extract,
    parse_vision_header_raw,
    persist_vision_header_to_invoice,
)
from app.services.invoice.vision_header_schema import VISION_HEADER_PROMPT_MARKERS
from app.services.prompt_registry.catalog import catalog_default_body
from app.services.tenant.tenant_org_context import OrgContext
from app.tenant_ids import TESTING_TENANT_UUID


def test_derive_canonical_from_handover_heading() -> None:
    assert (
        derive_canonical_document_type(
            document_heading="HANDOVER SLIP",
            canonical_document_type="",
        )
        == "Handover Slip"
    )
    assert (
        derive_canonical_document_type(
            document_heading="LETTER OF AUTHORIZATION",
            canonical_document_type="",
        )
        == "Letter of Authorization"
    )
    assert (
        derive_canonical_document_type(
            document_heading="ACME PTY LTD HANDOVER SLIP",
            canonical_document_type="",
        )
        == "Handover Slip"
    )
    assert (
        derive_canonical_document_type(
            document_heading="TAX INVOICE",
            canonical_document_type="Tax Invoice",
        )
        == "Tax Invoice"
    )


def test_parse_fills_canonical_when_model_leaves_non_finance_empty() -> None:
    """Older prompts blanked canonical for non-finance; derive from printed heading."""
    result = parse_vision_header_raw(
        {
            "document_heading": "HANDOVER SLIP",
            "canonical_document_type": "",
            "counterparty_name": "Site Ops",
            "perspective": "unknown",
            "invoice_no": "",
            "confidence": 0.82,
            "reason": "non-finance supporting form",
        },
        provider="claude_vision",
    )
    assert result.success is True
    assert result.canonical_document_type == "Handover Slip"

    loa = parse_vision_header_raw(
        {
            "document_heading": "Letter of Authorisation",
            "canonical_document_type": "",
            "counterparty_name": "",
            "perspective": "unknown",
            "confidence": 0.7,
            "reason": "ops form",
        },
        provider="claude_vision",
    )
    assert loa.canonical_document_type == "Letter of Authorisation"


def test_persist_derived_canonical_for_handover_slip() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "HANDOVER SLIP",
            "canonical_document_type": "",
            "counterparty_name": "Warehouse Co",
            "perspective": "unknown",
            "confidence": 0.8,
            "reason": "handover",
        },
        provider="claude_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    fields = inv.extracted_fields or {}
    assert fields.get("canonical_document_type") == "Handover Slip"
    assert fields.get("document_heading") == "HANDOVER SLIP"


def test_vision_header_prompt_names_supporting_docs() -> None:
    body = catalog_default_body("vision.header_extract.system") or ""
    assert "Supporting / ops / legal titles still get a canonical_document_type" in body
    assert 'Handover Slip / HANDOVER SLIP → "Handover Slip"' in body
    assert all(marker in body for marker in VISION_HEADER_PROMPT_MARKERS)


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
            "counterparty_name": "Classic Enterprise",
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
    assert inv.vendor == "Classic Enterprise"
    fields = inv.extracted_fields or {}
    assert fields.get("document_heading") == "Purchase Order"
    assert fields.get("seller_name") == "Classic Enterprise"


def test_persist_vision_header_preserve_keeps_clerk_total() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="USD",
        vendor="Classic Enterprise",
        total=Decimal("16000.00"),
        extracted_fields={"total": "16000.00"},
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX-CUM-COMMERCIAL INVOICE",
            "counterparty_name": "Classic Enterprise",
            "perspective": "purchase",
            "invoice_no": "CE-1",
            "total": "0",
            "currency": "",
            "confidence": 0.9,
            "reason": "invoice header",
        },
        provider="azure_foundry_vision",
    )
    persist_vision_header_to_invoice(inv, result, preserve_existing=True)
    assert inv.total == Decimal("16000.00")
    assert inv.currency == "USD"
    assert inv.vendor == "Classic Enterprise"
    assert (inv.extracted_fields or {}).get("total") == "16000.00"


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


def test_parse_posting_amounts_tax_ids_and_lines() -> None:
    from decimal import Decimal

    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "counterparty_name": "Acme Pty Ltd",
            "perspective": "purchase",
            "invoice_no": "INV-200",
            "invoice_date": "2026-03-15",
            "subtotal": "100.00",
            "gst": "10.00",
            "gst_rate": "10",
            "total": "110.00",
            "currency": "AUD",
            "seller_abn": "51 824 753 556",
            "buyer_abn": "29 002 588 189",
            "line_items": [
                {
                    "description": "Widget",
                    "qty": "2",
                    "unit_price": "50.00",
                    "amount": "100.00",
                    "tax_amount": "10.00",
                }
            ],
            "confidence": 0.92,
            "reason": "amounts labeled",
        },
        provider="claude_vision",
    )
    assert result.success is True
    assert result.subtotal == Decimal("100.00")
    assert result.gst == Decimal("10.00")
    assert result.gst_rate == Decimal("10")
    assert result.total == Decimal("110.00")
    assert result.seller_abn == "51824753556"
    assert result.buyer_abn == "29002588189"
    assert len(result.line_items) == 1
    assert result.line_items[0].description == "Widget"
    assert result.line_items[0].source == "vision_header"


def test_parse_tax_inclusive_only_leaves_breakdown_empty() -> None:
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "counterparty_name": "Acme",
            "perspective": "purchase",
            "invoice_no": "INV-1",
            "subtotal": "",
            "gst": "",
            "gst_rate": "",
            "total": "250.00",
            "currency": "AUD",
            "line_items": [],
            "confidence": 0.9,
            "reason": "tax inclusive only",
        },
        provider="claude_vision",
    )
    assert result.total is not None
    assert result.subtotal is None
    assert result.gst is None
    assert result.gst_rate is None
    assert result.line_items == ()


def test_parse_rejects_synthetic_grand_total_line() -> None:
    from decimal import Decimal

    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "total": "500.00",
            "line_items": [
                {"description": "", "qty": "", "unit_price": "", "amount": "500.00"},
                {"description": "Real item", "qty": "1", "unit_price": "10", "amount": "10.00"},
            ],
            "confidence": 0.8,
            "reason": "synthetic total row",
        },
        provider="claude_vision",
    )
    assert result.total == Decimal("500.00")
    assert len(result.line_items) == 1
    assert result.line_items[0].description == "Real item"


def test_parse_drops_junk_empty_line_rows() -> None:
    result = parse_vision_header_raw(
        {
            "total": "10.00",
            "line_items": [
                {"description": "", "qty": "", "amount": ""},
                {"description": "Kept", "qty": "1", "amount": "10.00"},
            ],
            "confidence": 0.7,
            "reason": "junk rows",
        },
        provider="claude_vision",
    )
    assert len(result.line_items) == 1
    assert result.line_items[0].description == "Kept"


def test_persist_posting_fields_and_valid_abn() -> None:
    from decimal import Decimal

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "canonical_document_type": "Tax Invoice",
            "counterparty_name": "Acme Pty Ltd",
            "perspective": "purchase",
            "invoice_no": "INV-300",
            "subtotal": "200.00",
            "gst": "20.00",
            "gst_rate": "10",
            "total": "220.00",
            "currency": "AUD",
            "seller_abn": "51824753556",
            "buyer_abn": "29002588189",
            "line_items": [
                {
                    "description": "Service",
                    "qty": "1",
                    "unit_price": "200.00",
                    "amount": "200.00",
                }
            ],
            "confidence": 0.9,
            "reason": "ok",
        },
        provider="claude_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.subtotal == Decimal("200.00")
    assert inv.gst == Decimal("20.00")
    assert inv.gst_rate == Decimal("10")
    assert inv.total == Decimal("220.00")
    assert inv.abn == "51824753556"
    fields = inv.extracted_fields or {}
    assert fields.get("subtotal") == "200.00"
    assert fields.get("gst") == "20.00"
    assert fields.get("seller_abn") == "51824753556"
    assert fields.get("buyer_abn") == "29002588189"
    assert fields.get("abn") == "51824753556"


def test_persist_invalid_abn_checksum_keeps_opaque_only() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "counterparty_name": "Acme",
            "perspective": "purchase",
            "invoice_no": "INV-1",
            "total": "100.00",
            "currency": "AUD",
            "seller_abn": "12345678901",
            "confidence": 0.9,
            "reason": "bad checksum",
        },
        provider="claude_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.abn is None or inv.abn == ""
    assert (inv.extracted_fields or {}).get("seller_abn") == "12345678901"


def test_persist_gstin_opaque_not_invoice_abn() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="INR",
    )
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "counterparty_name": "India Supplier",
            "perspective": "purchase",
            "invoice_no": "INV-9",
            "total": "1000.00",
            "currency": "INR",
            "seller_abn": "29AAACC1206D1ZM",
            "confidence": 0.88,
            "reason": "gstin",
        },
        provider="claude_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.abn is None or inv.abn == ""
    assert (inv.extracted_fields or {}).get("seller_abn") == "29AAACC1206D1ZM"


@pytest.mark.asyncio
async def test_clear_then_persist_keeps_vision_posting_fields() -> None:
    """Regression: understood-path clear runs before extract; values must stick."""
    from decimal import Decimal
    from unittest.mock import AsyncMock, MagicMock

    from app.services.invoice.invoice_reset import (
        clear_stale_not_understood_for_understood_path,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        subtotal=Decimal("999.00"),
        gst=Decimal("99.00"),
        gst_rate=Decimal("10"),
        abn="00000000000",
        extracted_fields={
            "subtotal": "999.00",
            "gst": "99.00",
            "seller_abn": "old",
            "buyer_abn": "old",
        },
    )
    session = AsyncMock()
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result_proxy)
    session.flush = AsyncMock()
    session.expire = MagicMock()

    await clear_stale_not_understood_for_understood_path(session, inv)
    assert inv.subtotal is None
    assert inv.gst is None
    assert inv.gst_rate is None
    assert inv.abn is None

    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "counterparty_name": "Acme",
            "perspective": "purchase",
            "invoice_no": "INV-KEEP",
            "subtotal": "100.00",
            "gst": "10.00",
            "gst_rate": "10",
            "total": "110.00",
            "currency": "AUD",
            "seller_abn": "51824753556",
            "line_items": [
                {"description": "Item A", "qty": "1", "amount": "100.00"},
            ],
            "confidence": 0.95,
            "reason": "after clear",
        },
        provider="claude_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.subtotal == Decimal("100.00")
    assert inv.gst == Decimal("10.00")
    assert inv.gst_rate == Decimal("10")
    assert inv.abn == "51824753556"
    assert (inv.extracted_fields or {}).get("seller_abn") == "51824753556"
    assert len(result.line_items) == 1


def test_pipeline_clears_stale_before_vision_header_extract() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app/services/invoice/pipeline.py"
    text = src.read_text(encoding="utf-8")
    clear_idx = text.index("clear_stale_not_understood_for_understood_path")
    header_idx = text.index("phase_vision_header_extract(")
    assert clear_idx < header_idx


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
        "app.services.invoice.vision_header_extract.resolve_header_vision_images",
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


def test_parse_vision_header_skips_cgst_sgst_line_rows() -> None:
    result = parse_vision_header_raw(
        {
            "document_heading": "TAX INVOICE",
            "counterparty_name": "MAKEMYTRIP",
            "total": "9800.53",
            "gst": "55.92",
            "currency": "INR",
            "line_items": [
                {"description": "Trip Assure Fee", "amount": "310.62"},
                {"description": "CGST @9%", "amount": "27.96"},
                {"description": "SGST @9%", "amount": "27.96"},
                {"description": "Grand Total", "amount": "9800.53"},
            ],
            "confidence": 0.9,
            "reason": "ok",
        },
        provider="claude_vision",
    )
    descs = [(li.description or "") for li in result.line_items]
    assert descs == ["Trip Assure Fee"]


@pytest.mark.asyncio
async def test_clear_stale_returns_prior_dt_and_snapshots() -> None:
    from decimal import Decimal
    from unittest.mock import AsyncMock, MagicMock

    from app.services.invoice.invoice_reset import (
        clear_stale_not_understood_for_understood_path,
        restore_prior_document_type_if_unmapped,
        restore_unrefilled_vision_stale_snapshot,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="INR",
        document_type_code="DT-04",
        document_type_confidence=0.91,
        subtotal=Decimal("100.00"),
        gst=Decimal("18.00"),
        gst_rate=Decimal("18"),
        abn=None,
        extracted_fields={
            "subtotal": "100.00",
            "gst": "18.00",
            "gst_rate": "18",
            "seller_abn": "29AAACC1206D1ZM",
            "canonical_document_type": "Tax Invoice",
            "azure_di_scalar_fields": {"x": 1},
        },
    )
    session = AsyncMock()
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result_proxy)
    session.flush = AsyncMock()
    session.expire = MagicMock()

    stale = await clear_stale_not_understood_for_understood_path(session, inv)
    assert stale["prior_document_type_code"] == "DT-04"
    assert stale["cleared_document_type"] is True
    assert inv.document_type_code is None
    assert inv.subtotal is None
    assert inv.gst is None
    assert "gst" in (stale.get("extracted_snapshot") or {})
    assert "seller_abn" in (stale.get("extracted_snapshot") or {})
    assert "azure_di_scalar_fields" not in (stale.get("extracted_snapshot") or {})
    # Non-restorable OCR artifact stripped; canonical kept.
    assert (inv.extracted_fields or {}).get("canonical_document_type") == "Tax Invoice"
    assert "azure_di_scalar_fields" not in (inv.extracted_fields or {})

    # Vision refill only gst — prior subtotal / seller_abn should come back.
    inv.gst = Decimal("18.00")
    inv.extracted_fields = {
        **(inv.extracted_fields or {}),
        "gst": "18.00",
    }
    retained = restore_unrefilled_vision_stale_snapshot(inv, stale)
    assert "subtotal" in retained["restored_columns"]
    assert "gst" not in retained["restored_columns"]
    assert inv.subtotal == Decimal("100.00")
    assert (inv.extracted_fields or {}).get("seller_abn") == "29AAACC1206D1ZM"
    assert "seller_abn" in retained["restored_extracted_keys"]

    # Remap empty → restore prior DT at capped confidence.
    restored = restore_prior_document_type_if_unmapped(inv, stale)
    assert restored["restored"] is True
    assert inv.document_type_code == "DT-04"
    assert float(inv.document_type_confidence) <= 0.35


def test_restore_prior_dt_skips_when_already_mapped() -> None:
    from app.services.invoice.invoice_reset import restore_prior_document_type_if_unmapped

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
        document_type_code="DT-01",
        document_type_confidence=0.8,
    )
    out = restore_prior_document_type_if_unmapped(
        inv,
        {"prior_document_type_code": "DT-04", "prior_document_type_confidence": 0.9},
    )
    assert out["restored"] is False
    assert out["reason"] == "already_mapped"
    assert inv.document_type_code == "DT-01"


def test_restore_skips_inconsistent_subtotal_when_total_set() -> None:
    from decimal import Decimal

    from app.services.invoice.invoice_reset import restore_unrefilled_vision_stale_snapshot

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        subtotal=None,
        gst=Decimal("0"),
        total=Decimal("6031.00"),
        currency="USD",
    )
    stale = {
        "column_snapshot": {"subtotal": Decimal("7712.47"), "gst": Decimal("0")},
        "extracted_snapshot": {"subtotal": "7712.47", "gst": "0.00"},
    }
    retained = restore_unrefilled_vision_stale_snapshot(inv, stale)
    assert "subtotal" not in retained["restored_columns"]
    assert "subtotal" not in retained["restored_extracted_keys"]
    assert inv.subtotal is None


def test_persist_clears_subtotal_when_result_subtotal_none() -> None:
    from decimal import Decimal

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        subtotal=Decimal("7712.47"),
        gst=Decimal("0"),
        total=Decimal("6031.00"),
        currency="USD",
        extracted_fields={"subtotal": "7712.47", "gst": "0.00", "total": "6031.00"},
    )
    result = VisionHeaderExtractResult(
        success=True,
        counterparty_name="3B SEMICONDUCTOR PVT LTD",
        invoice_no="SI-260571543",
        subtotal=None,
        gst=Decimal("0"),
        total=Decimal("6031.00"),
        currency="USD",
        confidence=0.9,
        provider="claude_vision",
    )
    persist_vision_header_to_invoice(inv, result)
    assert inv.subtotal is None
    assert inv.total == Decimal("6031.00")
    assert "subtotal" not in (inv.extracted_fields or {})
