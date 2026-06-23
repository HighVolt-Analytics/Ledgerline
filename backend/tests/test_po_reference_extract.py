"""PO reference extraction from OCR text."""

from app.services.po_reference import extract_po_reference_from_text


def test_extract_po_from_no_line() -> None:
    text = "Acme Corp PURCHASE ORDER\nNo: PO-2025-00142\nDate: 15 Jun 2025"
    assert extract_po_reference_from_text(text) == "PO-2025-00142"


def test_extract_po_from_inline_no_on_header_line() -> None:
    text = (
        "Acme Corp Pvt Ltd PURCHASE ORDER\n"
        "123 Business Park, India No: PO-2025-00142\n"
        "GSTIN: 36AABCA1234F1Z5"
    )
    assert extract_po_reference_from_text(text) == "PO-2025-00142"


def test_extract_po_from_purchase_order_number() -> None:
    text = "PURCHASE ORDER\nPurchase Order Number: MPL-PO-4456"
    assert extract_po_reference_from_text(text) == "MPL-PO-4456"
