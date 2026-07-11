"""Grounded extraction, manifest prompts, and no-assumption defaults."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_field_values import (
    build_extraction_field_manifest,
    build_smart_ocr_excerpt,
    enrich_parsed_from_ocr,
    filter_invoice_fields_for_keys,
    merge_gap_fill_into_parsed,
)
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.field_grounding_service import (
    _money_grounded_in_ocr,
    ground_invoice_scalars,
    ground_parsed_fields,
    value_grounded_in_ocr,
)
from app.services.extraction.gst_rate import resolve_gst_rate_percent
from app.services.extraction.llm_document_service import (
    _resolved_currency,
    build_extract_system_prompt,
    build_llm_user_payload,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.tenant.tenant_org_context import OrgContext


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="Tax Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(),
        extraction_fields=["vendor", "invoice_no", "total", "po_reference", "contract_party"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def test_build_extraction_field_manifest_lists_all_keys() -> None:
    manifest = build_extraction_field_manifest(
        ["vendor", "invoice_no", "contract_party", "bank_details"]
    )
    keys = {row["key"] for row in manifest}
    assert "vendor" in keys
    assert "invoice_no" in keys
    assert "contract_party" in keys
    assert "bank_bsb" in keys
    assert "bank_account" in keys


def test_build_extract_system_prompt_includes_manifest() -> None:
    keys = ["vendor", "invoice_no", "contract_party"]
    system = build_extract_system_prompt(OrgContext(), selected_keys=keys)
    assert "Finance field manifest" in system
    assert "`vendor`" in system
    assert "`invoice_no`" in system
    assert "`contract_party`" in system
    assert "Extract ONLY" in system


def test_build_smart_ocr_excerpt_includes_tail() -> None:
    head = "A" * 9000
    tail = "TOTAL 999.00"
    body = head + ("M" * 5000) + tail
    excerpt = build_smart_ocr_excerpt(body)
    assert excerpt.startswith("A" * 100)
    assert "TOTAL 999.00" in excerpt
    assert "\n...\n" in excerpt


def test_filter_invoice_fields_for_keys() -> None:
    filtered = filter_invoice_fields_for_keys(
        {"vendor": "Acme", "invoice_no": "INV-9", "total": "100"},
        ["vendor", "contract_party"],
    )
    assert filtered == {"vendor": "Acme"}


def test_build_llm_user_payload_includes_manifest() -> None:
    import json

    payload = json.loads(
        build_llm_user_payload(
            ocr=OcrArtifact(success=True, text="Vendor: Acme", text_length=12),
            org=OrgContext(),
            document_types=[_definition()],
            selected_keys=["vendor", "invoice_no"],
        )
    )
    assert payload["extraction_field_manifest"]
    assert {row["key"] for row in payload["extraction_field_manifest"]} >= {"vendor", "invoice_no"}
    assert "field_snippets" in payload["ocr"]


def test_ground_invoice_scalars_clears_ungrounded_invoice_no() -> None:
    ocr_text = "Vendor: Acme Pty Ltd\nTotal: 100.00"
    parsed = InvoiceData(vendor="Acme Pty Ltd", invoice_no="FAKE-999", total=Decimal("100"))
    grounded = ground_invoice_scalars(parsed, ocr_text)
    assert grounded.invoice_no is None
    assert grounded.vendor == "Acme Pty Ltd"
    assert grounded.total == Decimal("100")


def test_ground_parsed_fields_filters_unrequested_keys() -> None:
    parsed = InvoiceData(
        vendor="Acme",
        invoice_no="INV-1",
        total=Decimal("50"),
        extracted_fields={"contract_party": "Buyer"},
    )
    grounded = ground_parsed_fields(
        parsed,
        "Vendor: Acme\nInvoice No: INV-1\nTotal: 50\nContract Party: Buyer",
        ["vendor", "total"],
    )
    assert grounded.invoice_no is None
    assert grounded.vendor == "Acme"
    assert "contract_party" not in grounded.extracted_fields


def test_ground_parsed_fields_keeps_configured_account_code() -> None:
    parsed = InvoiceData(
        vendor="Acme",
        extracted_fields={"account_code": "6100"},
    )
    grounded = ground_parsed_fields(
        parsed,
        "Vendor: Acme\nAccount Code: 6100",
        ["vendor", "account_code"],
    )
    assert grounded.extracted_fields.get("account_code") == "6100"


def test_enrich_parsed_from_ocr_grounded_backfill_po_reference() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nPO: 12345\nVendor: Acme",
        text_length=40,
    )
    parsed = InvoiceData(document_text=ocr.text)
    enriched = enrich_parsed_from_ocr(parsed, ocr, dt_definition=_definition())
    assert enriched.po_reference == "12345"


def test_merge_extraction_sources_preserves_llm_when_di_ungrounded() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nVendor: Real Co",
        text_length=25,
        payload_json={
            "invoice_fields": {
                "vendor": "Hallucinated Vendor",
                "invoice_no": "INV-1",
            }
        },
    )
    parsed = InvoiceData(vendor="Real Co", document_text=ocr.text)
    merged = merge_extraction_sources(parsed, ocr, dt_definition=_definition())
    assert merged.vendor == "Real Co"
    assert merged.invoice_no is None


def test_resolved_currency_no_aud_default() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-01",
        confidence=0.9,
        subtotal=Decimal("100"),
        total=Decimal("110"),
        currency="",
    )
    assert _resolved_currency(llm) == ""


def test_resolve_gst_rate_no_inference_without_ocr_rate() -> None:
    parsed = InvoiceData(subtotal=Decimal("100"), gst=Decimal("10"))
    rate = resolve_gst_rate_percent(
        parsed,
        ocr_text="Subtotal 100.00\nGST 10.00\nTotal 110.00",
        allow_inference=False,
    )
    assert rate is None


def test_resolve_gst_rate_keeps_explicit_rate_when_grounded() -> None:
    parsed = InvoiceData(subtotal=Decimal("100"), gst=Decimal("10"), gst_rate=Decimal("10"))
    rate = resolve_gst_rate_percent(
        parsed,
        ocr_text="GST Rate: 10%\nSubtotal 100.00",
        allow_inference=False,
    )
    assert rate == Decimal("10")


def test_value_grounded_rejects_placeholder_abn() -> None:
    assert not value_grounded_in_ocr("45123456789", "ABN 45123456789")


def test_merge_gap_fill_keeps_grounded_po_reference() -> None:
    ocr_text = "TAX INVOICE\nPO: 12345\nVendor: Acme"
    parsed = InvoiceData(document_text=ocr_text)
    gap = InvoiceData(po_reference="12345", document_text=ocr_text)
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["po_reference"],
        ocr_text=ocr_text,
    )
    assert result.parsed.po_reference == "12345"
    assert result.filled == ("po_reference",)


def test_merge_gap_fill_clears_hallucinated_vendor() -> None:
    ocr_text = "TAX INVOICE\nVendor: Real Co"
    parsed = InvoiceData(document_text=ocr_text)
    gap = InvoiceData(vendor="Invented Vendor", document_text=ocr_text)
    result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=["vendor"],
        ocr_text=ocr_text,
    )
    assert not result.parsed.vendor
    assert result.rejected == ("vendor",)


def test_money_grounded_currency_symbol_and_commas() -> None:
    ocr = "Invoice total $1,234.56 due"
    assert _money_grounded_in_ocr(Decimal("1234.56"), ocr, field_key="total")


def test_money_grounded_adjacent_line_balance_due() -> None:
    ocr = "Line items\nBalance due\n1,234.56"
    assert _money_grounded_in_ocr(Decimal("1234.56"), ocr, field_key="total")


def test_money_grounded_rejects_ungrounded_amount() -> None:
    ocr = "Balance due\n500.00"
    assert not _money_grounded_in_ocr(Decimal("999.99"), ocr, field_key="total")


def test_vendor_fuzzy_grounding_normalized_casing() -> None:
    ocr = "TAX INVOICE\nACME PTY LTD\nTotal: 100.00"
    assert value_grounded_in_ocr("Acme Pty Ltd", ocr)


def test_ground_invoice_scalars_sanitizes_invoice_no_bleed_and_fills_date() -> None:
    from datetime import date

    from app.services.extraction.field_grounding_service import ground_invoice_scalars

    ocr = "PROFORMA INVOICE NO: 2603110950SA DATED: 11.05.2026"
    parsed = InvoiceData(invoice_no="2603110950SA DATED: 11.05.2026")
    grounded = ground_invoice_scalars(parsed, ocr)
    assert grounded.invoice_no == "2603110950SA"
    assert grounded.invoice_date == date(2026, 5, 11)


def test_label_proximate_grounding_prefers_labeled_invoice_no() -> None:
    ocr = """
Purchase Order PO-INV-12345 reference
Invoice No: INV-12345
Total 100.00
"""
    debug: dict[str, str] = {}
    assert value_grounded_in_ocr("INV-12345", ocr, field_key="invoice_no", grounding_debug=debug)
    assert debug.get("invoice_no") == "label_proximate"
    assert value_grounded_in_ocr("INV-12345", ocr) is True


def test_label_proximate_without_field_key_uses_substring() -> None:
    ocr = "Invoice No: INV-999\nPO-INV-999 elsewhere"
    debug: dict[str, str] = {}
    assert value_grounded_in_ocr("INV-999", ocr, grounding_debug=debug)
    assert "INV-999" not in debug
