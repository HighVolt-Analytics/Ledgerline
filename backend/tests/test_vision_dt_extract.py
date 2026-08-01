"""Unit tests for DT-scoped vision extract helpers."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.extraction.extraction_field_values import effective_extraction_field_keys_for_dt
from app.services.invoice.vision_dt_extract import _minimal_vision_ocr


def test_minimal_vision_ocr_is_sparse_for_image_attach() -> None:
    ocr = _minimal_vision_ocr(page_count=2)
    assert ocr.success is True
    assert ocr.sparse is True
    assert ocr.text == ""


def test_vision_dt_extract_audit_includes_line_item_counts() -> None:
    from app.services.invoice.vision_dt_extract import (
        VisionDtExtractResult,
        vision_dt_extract_audit_detail,
    )

    detail = vision_dt_extract_audit_detail(
        VisionDtExtractResult(
            success=True,
            selected_keys=("line_items", "currency"),
            line_items_count=1,
            line_items_fallback="fallback_pdf_tables",
        )
    )
    assert detail["line_items_count"] == 1
    assert detail["line_items_fallback"] == "fallback_pdf_tables"


def test_dt_scoped_keys_come_from_document_type_extraction_fields() -> None:
    dts = [
        DocumentTypeDefinition(
            code="DT-99",
            name="Test Claim",
            title="Test Claim",
            short_title="Claim",
            klass="Expense",
            posting="Yes",
            enabled=True,
            extraction_fields=["vendor", "total", "invoice_date", "due_date"],
            required_fields=["vendor", "total"],
        )
    ]
    keys = effective_extraction_field_keys_for_dt(dts, "DT-99")
    assert "vendor" in keys
    assert "total" in keys
    assert "invoice_date" in keys
    # Fixed vision header schema must not be the source of truth.
    assert "vendor" in keys


def test_filter_parsed_drops_unconfigured_party_fields() -> None:
    from app.services.extraction.extraction_field_values import filter_parsed_to_requested_keys
    from app.services.invoice.invoice_data import InvoiceData

    parsed = InvoiceData(
        vendor="Everest",
        billing_address="100 Industrial Ave",
        extracted_fields={
            "vendor": "Everest",
            "seller_name": "Everest Furnishings Pty Ltd",
            "seller_abn": "98 765 432 109",
            "buyer_name": "Highvolt",
            "billing_address": "100 Industrial Ave",
            "total": "5500",
        },
    )
    filtered = filter_parsed_to_requested_keys(
        parsed,
        ["vendor", "invoice_no", "po_reference", "total", "gst", "subtotal"],
    )
    assert filtered.vendor == "Everest"
    assert filtered.billing_address is None
    assert "seller_name" not in (filtered.extracted_fields or {})
    assert "buyer_name" not in (filtered.extracted_fields or {})
    assert (filtered.extracted_fields or {}).get("vendor") == "Everest"
    assert (filtered.extracted_fields or {}).get("total") == "5500"
