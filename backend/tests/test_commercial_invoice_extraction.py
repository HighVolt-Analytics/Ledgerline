"""Commercial / export invoice extraction: per-field DI hybrid, charge lines, invoice_no cleanup."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.extraction_field_values import (
    apply_di_scalars_authoritative,
    clear_llm_scalars_for_di_populated_fields,
    di_scalar_fields_populated,
    field_di_authoritative,
)
from app.services.extraction.invoice_no_sanitizer import extract_invoice_no_from_text, sanitize_invoice_no
from app.services.extraction.line_items_parser import (
    document_has_charge_lines,
    parse_charge_lines_from_text,
)
from app.services.invoice.invoice_data import InvoiceData


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="Commercial Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(),
        extraction_fields=["invoice_no", "total", "line_items", "vendor"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


_COMMERCIAL_OCR = """
COMMERCIAL INVOICE
DESCRIPTION OF GOODS AND/ OR SERVICES: COMPUTER PARTS AND ACCESSORIES
FREIGHT: USD 400.00 (INCLUDED)
PROFORMA INVOICE NO: RC-SIPL-AUG-INL-20250826-001, DATED: 26.08.2025 OF THE BENEFICIARY.
"""


def test_sanitize_invoice_no_strips_dated_bleed() -> None:
    raw = "RC-SIPL-AUG-INL-20250826-001, DATED: 26.08.2025 OF THE BENEFICIARY"
    assert sanitize_invoice_no(raw) == "RC-SIPL-AUG-INL-20250826-001"


def test_extract_invoice_no_from_proforma_line() -> None:
    assert (
        extract_invoice_no_from_text(
            "PROFORMA INVOICE NO: RC-SIPL-AUG-INL-20250826-001, DATED: 26.08.2025"
        )
        == "RC-SIPL-AUG-INL-20250826-001"
    )


def test_di_scalar_fields_populated_only_non_empty() -> None:
    payload = {
        "invoice_fields": {
            "vendor": "Acme",
            "invoice_no": "INV-1",
            "total": None,
            "po_reference": "",
        }
    }
    populated = di_scalar_fields_populated(payload)
    assert populated == {"vendor", "invoice_no"}
    assert not field_di_authoritative(payload, "total")
    assert field_di_authoritative(payload, "invoice_no")


def test_merge_commercial_invoice_freight_total_from_ocr() -> None:
    ocr = OcrArtifact(
        success=True,
        text=_COMMERCIAL_OCR,
        text_length=len(_COMMERCIAL_OCR),
        payload_json={
            "invoice_fields": {
                "vendor": "Exporter Co",
                "invoice_no": "RC-SIPL-AUG-INL-20250826-001, DATED: 26.08.2025 OF THE BEN",
                "total": None,
            },
            "di_scalar_sources": {"vendor": "VendorName", "invoice_no": "InvoiceId"},
        },
    )
    parsed = InvoiceData(document_text=ocr.text, total=None)
    merged = merge_extraction_sources(parsed, ocr, dt_definition=_definition())
    assert merged.invoice_no == "RC-SIPL-AUG-INL-20250826-001"
    assert merged.total == Decimal("400")


def test_merge_commercial_invoice_charge_line_items() -> None:
    ocr = OcrArtifact(
        success=True,
        text=_COMMERCIAL_OCR,
        text_length=len(_COMMERCIAL_OCR),
        payload_json={"invoice_fields": {"vendor": "Exporter", "total": None}},
    )
    parsed = InvoiceData(document_text=ocr.text)
    merged = merge_extraction_sources(
        parsed,
        ocr,
        dt_definition=_definition(extraction_fields=["line_items", "total"]),
    )
    assert document_has_charge_lines(ocr.text)
    assert len(merged.line_items) >= 1
    freight_rows = [row for row in merged.line_items if row.description == "Freight"]
    assert freight_rows
    assert freight_rows[0].amount == Decimal("400")


def test_parse_charge_lines_from_text() -> None:
    items = parse_charge_lines_from_text(_COMMERCIAL_OCR)
    assert any(row.description == "Freight" and row.amount == Decimal("400") for row in items)
    assert any("COMPUTER PARTS" in (row.description or "") for row in items)


def test_clear_llm_only_di_populated_fields() -> None:
    parsed = InvoiceData(
        vendor="LLM Vendor",
        invoice_no="LLM-1",
        total=Decimal("999"),
    )
    payload = {
        "invoice_fields": {"vendor": "DI Vendor", "total": None},
    }
    cleared = clear_llm_scalars_for_di_populated_fields(
        parsed,
        ["vendor", "invoice_no", "total"],
        payload,
    )
    assert cleared.vendor is None
    assert cleared.invoice_no == "LLM-1"
    assert cleared.total == Decimal("999")


def test_apply_di_scalars_only_populated_keys() -> None:
    parsed = InvoiceData(vendor="Old", total=Decimal("50"), invoice_no="KEEP")
    payload = {
        "invoice_fields": {"vendor": "DI Vendor", "total": None, "invoice_no": None},
    }
    merged = apply_di_scalars_authoritative(parsed, payload, ["vendor", "total", "invoice_no"])
    assert merged.vendor == "DI Vendor"
    assert merged.total == Decimal("50")
    assert merged.invoice_no == "KEEP"
