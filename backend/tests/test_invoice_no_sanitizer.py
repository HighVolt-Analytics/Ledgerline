"""Unit tests for conservative invoice_no sanitization."""

from __future__ import annotations

from app.services.extraction.field_grounding_service import ground_invoice_scalars
from app.services.extraction.invoice_no_sanitizer import (
    INVOICE_NO_SECONDARY_KEY,
    extract_invoice_no_from_text,
    invoice_no_dup_tokens_from_values,
    invoice_no_link_tokens_from_values,
    sanitize_invoice_no,
    sanitize_invoice_no_parts,
)
from app.services.invoice.invoice_data import InvoiceData


def test_extract_inv_no_label_from_clearance_permit_style() -> None:
    text = (
        "PERMIT NO : OD5I458006S\n"
        "UNITS (INV NO: 250970286) 5622.17\n"
        "UNIQUE REF : 197700341D 20250905 5701\n"
    )
    assert extract_invoice_no_from_text(text) == "250970286"


def test_extract_leaves_invoice_no_empty_when_only_permit() -> None:
    text = "CARGO CLEARANCE PERMIT\nPERMIT NO : OD5I458006S\n"
    assert extract_invoice_no_from_text(text) is None
    from app.services.extraction.invoice_no_sanitizer import (
        extract_permit_or_doc_no_from_text,
    )

    assert extract_permit_or_doc_no_from_text(text) == "OD5I458006S"


def test_sanitize_strips_date_bleed_label() -> None:
    assert sanitize_invoice_no("INV-123 Date: 11/05/2026") == "INV-123"


def test_sanitize_strips_gstin_bleed() -> None:
    assert sanitize_invoice_no("INV-99 GSTIN: 29AAAAA0000A1Z5") == "INV-99"


def test_sanitize_strips_leading_hash() -> None:
    assert sanitize_invoice_no("#0001") == "0001"
    assert sanitize_invoice_no("Invoice Number: #0001") == "0001"


def test_extract_invoice_number_label_with_hash() -> None:
    assert extract_invoice_no_from_text("Invoice Number: #0001\nTotal $10") == "0001"
    assert (
        extract_invoice_no_from_text(
            "Invoice Number: 686b6174909b5272abdce254\nTotal US$37.08"
        )
        == "686b6174909b5272abdce254"
    )



def test_sanitize_normalizes_en_dash() -> None:
    assert sanitize_invoice_no("INV–2026–0589") == "INV-2026-0589"


def test_sanitize_dated_bleed_still_works() -> None:
    raw = "RC-SIPL-AUG-INL-20250826-001, DATED: 26.08.2025 OF THE BENEFICIARY"
    assert sanitize_invoice_no(raw) == "RC-SIPL-AUG-INL-20250826-001"
    assert sanitize_invoice_no("2603110950SA DATED: 11.05.2026") == "2603110950SA"
    assert sanitize_invoice_no("260371344/") == "260371344"


def test_preserve_compound_slash_forms() -> None:
    assert sanitize_invoice_no("SI/2025-26/001") == "SI/2025-26/001"
    assert sanitize_invoice_no("RC-SIPL-AUG-INL-20250826-001") == "RC-SIPL-AUG-INL-20250826-001"
    assert sanitize_invoice_no("00045821") == "00045821"
    assert sanitize_invoice_no("2603110950SA") == "2603110950SA"
    assert sanitize_invoice_no("INV-100/2025") == "INV-100/2025"


def test_dual_numeric_slash_keeps_both() -> None:
    primary, secondary = sanitize_invoice_no_parts("203946589/295837465")
    assert primary == "203946589"
    assert secondary == "295837465"
    assert sanitize_invoice_no("203946589/295837465") == "203946589"


def test_reject_date_money_junk_gstin() -> None:
    assert sanitize_invoice_no("11.05.2026") is None
    assert sanitize_invoice_no("1,234.56") is None
    assert sanitize_invoice_no("ORIGINAL") is None
    assert sanitize_invoice_no("29AAAAA0000A1Z5") is None


def test_reject_packing_list_column_header_as_invoice_no() -> None:
    """Adjacent 'Customer PO' header must never become invoice_no."""
    assert sanitize_invoice_no("Customer") is None
    assert sanitize_invoice_no("customer") is None
    assert sanitize_invoice_no("Customer PO") is None
    assert sanitize_invoice_no("Incoterm") is None
    assert sanitize_invoice_no("Invoice No Customer") is None
    assert sanitize_invoice_no("Customer 82507681") == "82507681"


def test_extract_skips_customer_po_header_bleed() -> None:
    """Lexar-style packing list: Invoice No. | Customer PO reading-order bleed."""
    text = (
        "PACKING LIST\n"
        "Date PackingList No. Invoice No. Customer PO Incoterm\n"
        "2025-07-25 0000078729 82507681 PO-250742524 EXW Hong Kong\n"
    )
    assert extract_invoice_no_from_text(text) == "82507681"

    bleed = (
        "PACKING LIST\n"
        "Invoice No. Customer PO\n"
        "82507681 PO-250742524\n"
    )
    assert extract_invoice_no_from_text(bleed) == "82507681"

    glued = "Invoice No Customer\n82507681 SPECTRA\n"
    assert extract_invoice_no_from_text(glued) == "82507681"


def test_extract_prefers_commercial_over_proforma() -> None:
    text = (
        "PROFORMA INVOICE NO: PF-999\n"
        "Invoice No: INV-2026-0589\n"
    )
    assert extract_invoice_no_from_text(text) == "INV-2026-0589"


def test_link_and_dup_tokens_include_both() -> None:
    link = invoice_no_link_tokens_from_values("203946589", "295837465")
    assert "203946589" in link
    assert "295837465" in link
    dup = invoice_no_dup_tokens_from_values("203946589", "295837465")
    assert "203946589" in dup
    assert "295837465" in dup


def test_grounding_sets_secondary_extracted_field() -> None:
    ocr = "Invoice No: 203946589/295837465\nTotal 100.00"
    parsed = InvoiceData(invoice_no="203946589/295837465")
    grounded = ground_invoice_scalars(parsed, ocr)
    assert grounded.invoice_no == "203946589"
    assert grounded.extracted_fields.get(INVOICE_NO_SECONDARY_KEY) == "295837465"
