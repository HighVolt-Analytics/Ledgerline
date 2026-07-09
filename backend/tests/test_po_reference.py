"""PO reference extraction and resolution."""

from app.models.invoice import Invoice
from app.services.extraction.extraction_field_values import apply_parsed_extraction_fields
from app.services.invoice.invoice_data import InvoiceData
from app.services.purchase.po_reference import (
    ensure_invoice_po_reference,
    extract_po_reference_from_text,
    is_plausible_po_reference,
    resolve_po_reference_from_invoice,
)


def test_multiline_ocr_junk_not_plausible_po_reference() -> None:
    junk = "WALTON DIGI-TECH INDUSTRIES LIMITED\nPO NO. : 45001234"
    assert is_plausible_po_reference(junk) is False
    inv = Invoice(po_reference=junk)
    assert ensure_invoice_po_reference(inv) is None
    assert inv.po_reference is None


def test_po_reference_truncated_to_column_limit() -> None:
    long_ref = "PO-" + ("A" * 120)
    inv = Invoice(po_reference=long_ref[:64])
    assert ensure_invoice_po_reference(inv) is not None
    assert inv.po_reference is not None
    assert len(inv.po_reference) <= 100


def test_apply_parsed_extraction_fields_drops_junk_po_reference() -> None:
    inv = Invoice()
    parsed = InvoiceData(
        extracted_fields={"po_reference": "Vendor header\nPO 12345"},
        currency="AUD",
    )
    apply_parsed_extraction_fields(inv, parsed)
    assert inv.extracted_fields is None or "po_reference" not in (inv.extracted_fields or {})


def test_resolve_po_reference_from_text() -> None:
    inv = Invoice(document_text="Purchase Order Number: PO-998877")
    assert resolve_po_reference_from_invoice(inv) == "PO-998877"


def test_extract_po_reference_from_text_helper() -> None:
    assert extract_po_reference_from_text("Purchase Order No. PO-445566") == "PO-445566"
