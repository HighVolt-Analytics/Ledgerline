"""SO reference extraction and resolution."""

from app.models.invoice import Invoice
from app.services.extraction_field_values import apply_parsed_extraction_fields
from app.services.invoice_data import InvoiceData
from app.services.so_reference import (
    ensure_invoice_so_reference,
    extract_so_reference_from_filename,
    resolve_so_reference_from_invoice,
)


def test_extract_so_reference_from_filename() -> None:
    assert extract_so_reference_from_filename("sales_order_SO-DEMO-100.pdf") == "SO-DEMO-100"
    assert extract_so_reference_from_filename("delivery_note_SO-DEMO-100.pdf") == "SO-DEMO-100"
    assert extract_so_reference_from_filename("invoice.pdf") is None


def test_resolve_so_reference_from_filename() -> None:
    inv = Invoice(
        email_attachment_name="sales_order_SO-DEMO-100.pdf",
        route_target="Sales Management",
    )
    assert resolve_so_reference_from_invoice(inv) == "SO-DEMO-100"


def test_ensure_invoice_so_reference_persists_column() -> None:
    inv = Invoice(email_attachment_name="SO-7788.pdf")
    assert ensure_invoice_so_reference(inv) == "SO-7788"
    assert inv.so_reference == "SO-7788"


def test_apply_parsed_extraction_fields_promotes_so_reference() -> None:
    inv = Invoice(email_attachment_name="delivery_note_SO-9001.pdf")
    parsed = InvoiceData(
        extracted_fields={"so_reference": "SO-9001"},
        currency="AUD",
    )
    apply_parsed_extraction_fields(inv, parsed)
    assert inv.so_reference == "SO-9001"
