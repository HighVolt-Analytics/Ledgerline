"""DI-first scalar extraction: finance-aware prompts and exact DI mapping."""

from __future__ import annotations

import json
from decimal import Decimal

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.document_intelligence import _map_di_document
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.extraction_field_values import (
    apply_di_scalars_authoritative,
    build_finance_field_manifest,
    build_scalar_fields_presentation_prompt,
    clear_llm_scalars_for_di,
    normalize_di_scalars_for_prompt,
    prebuilt_invoice_scalars_active,
    resolve_scalars_from_ocr_payload,
)
from app.services.extraction.field_grounding_service import ground_parsed_fields
from app.services.extraction.llm_document_service import (
    build_extract_system_prompt,
    build_llm_user_payload,
    llm_result_to_invoice_data,
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
        extraction_fields=["vendor", "abn", "invoice_no", "total", "currency", "po_reference"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


class _FakeField:
    def __init__(self, value: object) -> None:
        self.value_string = value


class _FakeDoc:
    def __init__(self, fields: dict) -> None:
        self.fields = fields


def test_map_di_document_vendor_abn_not_customer() -> None:
    doc = _FakeDoc(
        {
            "VendorName": _FakeField("Acme Pty Ltd"),
            "VendorTaxId": _FakeField("12 345 678 901"),
            "CustomerName": _FakeField("Highvolt Pty Ltd"),
            "CustomerTaxId": _FakeField("98 765 432 109"),
            "InvoiceId": _FakeField("INV-1"),
            "InvoiceTotal": _FakeField("110.00"),
        }
    )
    data = _map_di_document(doc)
    assert data.vendor == "Acme Pty Ltd"
    assert data.abn == "12345678901"
    assert data.extracted_fields.get("buyer_name") == "Highvolt Pty Ltd"
    assert data.extracted_fields.get("buyer_tax_id") == "98765432109"
    assert data.extracted_fields.get("seller_name") == "Acme Pty Ltd"


def test_map_di_document_no_currency_default() -> None:
    doc = _FakeDoc(
        {
            "VendorName": _FakeField("Acme"),
            "InvoiceId": _FakeField("INV-2"),
            "InvoiceTotal": _FakeField("100"),
        }
    )
    data = _map_di_document(doc)
    assert data.currency == ""


def test_prebuilt_invoice_scalars_active() -> None:
    assert not prebuilt_invoice_scalars_active({"invoice_fields": {}})
    assert not prebuilt_invoice_scalars_active({})
    assert prebuilt_invoice_scalars_active(
        {"invoice_fields": {"vendor": "Acme", "total": "10.00"}}
    )


def test_resolve_scalars_from_ocr_payload() -> None:
    payload = {
        "invoice_fields": {
            "vendor": "Acme",
            "invoice_no": "INV-1",
            "total": "100.00",
            "currency": "",
        }
    }
    data = resolve_scalars_from_ocr_payload(payload, ["vendor", "invoice_no", "total"])
    assert data is not None
    assert data.vendor == "Acme"
    assert data.invoice_no == "INV-1"
    assert data.total == Decimal("100")


def test_normalize_di_scalars_for_prompt_includes_source() -> None:
    payload = {
        "invoice_fields": {
            "vendor": "Acme",
            "invoice_no": "INV-1",
            "total": "100.00",
        },
        "di_scalar_sources": {
            "vendor": "VendorName",
            "invoice_no": "InvoiceId",
            "total": "InvoiceTotal",
        },
    }
    block = normalize_di_scalars_for_prompt(payload, ["vendor", "invoice_no", "total"])
    assert block["vendor"]["value"] == "Acme"
    assert block["vendor"]["di_azure_source"] == "VendorName"
    assert block["total"]["di_azure_source"] == "InvoiceTotal"


def test_build_finance_field_manifest_includes_do_not_use() -> None:
    manifest = build_finance_field_manifest(["vendor", "subtotal"])
    by_key = {row["key"]: row for row in manifest}
    assert "do_not_use" in by_key["vendor"]
    vendor_do_not_use = by_key["vendor"]["do_not_use"].lower()
    assert "buyer" in vendor_do_not_use or "customer" in vendor_do_not_use
    assert "finance_role" in by_key["subtotal"]
    assert by_key["vendor"].get("deprioritized_labels") is not None


def test_build_scalar_fields_presentation_prompt_di_mode() -> None:
    lines = build_scalar_fields_presentation_prompt(di_active=True)
    joined = "\n".join(lines)
    assert "azure_di_scalar_fields" in joined
    assert "NEVER default currency" in joined


def test_ground_parsed_fields_clears_llm_scalars_when_di_active() -> None:
    ocr_text = "TAX INVOICE\nAcme\nInvoice No: INV-1\nTotal: 100.00"
    parsed = InvoiceData(vendor="LLM Wrong", invoice_no="FAKE", total=Decimal("999"))
    payload = {"invoice_fields": {"vendor": "Acme", "invoice_no": "INV-1", "total": "100"}}
    grounded = ground_parsed_fields(
        parsed, ocr_text, ["vendor", "invoice_no", "total"], payload
    )
    assert grounded.vendor is None
    assert grounded.invoice_no is None
    assert grounded.total is None


def test_ground_parsed_fields_keeps_llm_when_di_ungrounded() -> None:
    ocr_text = "TAX INVOICE\nVendor: Real Co\nInvoice No: INV-1\nTotal: 100.00"
    parsed = InvoiceData(vendor="Real Co", invoice_no="INV-1", total=Decimal("100"))
    payload = {"invoice_fields": {"vendor": "Hallucinated Vendor", "total": "999"}}
    grounded = ground_parsed_fields(
        parsed, ocr_text, ["vendor", "invoice_no", "total"], payload
    )
    assert grounded.vendor == "Real Co"
    assert grounded.invoice_no == "INV-1"
    assert grounded.total == Decimal("100")


def test_merge_extraction_sources_di_wins_over_llm() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nAcme Pty Ltd\nInvoice No: INV-1\nTotal: 100.00",
        text_length=50,
        payload_json={
            "invoice_fields": {
                "vendor": "Acme Pty Ltd",
                "invoice_no": "INV-1",
                "total": "100.00",
            },
            "di_scalar_sources": {
                "vendor": "VendorName",
                "invoice_no": "InvoiceId",
                "total": "InvoiceTotal",
            },
        },
    )
    parsed = InvoiceData(
        vendor="Hallucinated",
        invoice_no="WRONG",
        total=Decimal("999"),
        document_text=ocr.text,
    )
    merged = merge_extraction_sources(parsed, ocr, dt_definition=_definition())
    assert merged.vendor == "Acme Pty Ltd"
    assert merged.invoice_no == "INV-1"
    assert merged.total == Decimal("100")


def test_merge_di_empty_po_allows_ocr_fill() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nAcme\nPO: 99999\nInvoice No: INV-1",
        text_length=40,
        payload_json={
            "invoice_fields": {
                "vendor": "Acme",
                "invoice_no": "INV-1",
                "po_reference": None,
            },
        },
    )
    parsed = InvoiceData(
        vendor="Acme",
        invoice_no="INV-1",
        po_reference=None,
        document_text=ocr.text,
    )
    merged = merge_extraction_sources(
        parsed,
        ocr,
        dt_definition=_definition(extraction_fields=["vendor", "invoice_no", "po_reference"]),
    )
    assert merged.po_reference == "99999"


def test_llm_result_skips_scalars_when_di_trusted() -> None:
    llm = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-01",
            "confidence": 0.9,
            "vendor": "LLM Wrong",
            "seller": {"name": "LLM Wrong"},
            "invoice_no": "INV-99",
            "total": "999",
        }
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(
            success=True,
            text="TAX INVOICE\nAcme\nInvoice No: INV-99\nTotal: 100",
            text_length=40,
            payload_json={"invoice_fields": {"vendor": "Acme", "total": "100"}},
        ),
        selected_keys=["vendor", "invoice_no", "total"],
    )
    assert parsed.vendor == "Acme"
    assert parsed.invoice_no == "INV-99"
    assert parsed.total is not None
    assert str(parsed.total) in {"100", "100.0"}
    assert parsed.extracted_fields.get("vendor") == "Acme"


def test_build_llm_user_payload_azure_di_scalar_fields() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Invoice",
        text_length=7,
        payload_json={
            "invoice_fields": {
                "vendor": "Acme",
                "invoice_no": "INV-1",
                "total": "100.00",
            },
            "di_scalar_sources": {"vendor": "VendorName", "invoice_no": "InvoiceId"},
        },
    )
    raw = build_llm_user_payload(
        ocr=ocr,
        org=OrgContext(),
        document_types=[_definition()],
        selected_keys=["vendor", "invoice_no", "total"],
    )
    payload = json.loads(raw)
    assert payload["ocr"]["scalar_fields_source"] == "azure_di"
    assert payload["ocr"]["azure_di_scalar_fields"]["vendor"]["value"] == "Acme"
    assert "field_snippets" in payload["ocr"]
    assert "invoice_fields" not in payload
    assert payload["finance_field_manifest"]


def test_build_extract_system_prompt_finance_manifest() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Invoice",
        text_length=7,
        payload_json={"invoice_fields": {"vendor": "Acme"}},
    )
    system = build_extract_system_prompt(
        OrgContext(),
        selected_keys=["vendor", "total"],
        ocr=ocr,
    )
    assert "Finance field manifest" in system
    assert "AZURE DI" in system


def test_apply_di_scalars_authoritative_overwrites() -> None:
    parsed = InvoiceData(vendor="Old", total=Decimal("1"))
    payload = {
        "invoice_fields": {"vendor": "New Vendor", "total": "200.00"},
    }
    merged = apply_di_scalars_authoritative(
        parsed,
        payload,
        ["vendor", "total"],
        ocr_text="Vendor: New Vendor\nTotal: 200.00",
    )
    assert merged.vendor == "New Vendor"
    assert merged.total == Decimal("200")


def test_clear_llm_scalars_for_di_populated_only() -> None:
    parsed = InvoiceData(
        vendor="X",
        currency="USD",
        invoice_no="KEEP",
        extracted_fields={"seller_name": "X"},
    )
    payload = {"invoice_fields": {"vendor": "DI Vendor", "currency": ""}}
    ocr_text = "Vendor: DI Vendor\nInvoice No: KEEP"
    cleared = clear_llm_scalars_for_di(
        parsed,
        ["vendor", "currency", "invoice_no", "seller_name"],
        payload,
        ocr_text=ocr_text,
    )
    assert cleared.vendor is None
    assert cleared.currency == "USD"
    assert cleared.invoice_no == "KEEP"
