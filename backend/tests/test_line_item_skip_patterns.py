"""Tests for shared line-item skip patterns."""

from app.services.extraction.line_item_skip_patterns import (
    is_metadata_line_description,
    is_summary_line_description,
    should_skip_line_row,
)


def test_summary_line_matches_totals_not_product_names() -> None:
    assert is_summary_line_description("Sub Total")
    assert is_summary_line_description("GST")
    assert is_summary_line_description("Total")
    assert is_summary_line_description("TOTAL NO. OF PALLET :")
    assert is_summary_line_description("Balance Due $1,200.00")
    assert is_summary_line_description("Net Payable")
    assert is_summary_line_description("Total GST 150.00")
    assert is_summary_line_description("CGST @ 9%")
    assert is_summary_line_description("SGST @ 9%")
    assert is_summary_line_description("IGST @ 18%")
    assert is_summary_line_description("Round Off")
    assert is_summary_line_description("Round Off 0.05")
    assert is_summary_line_description("Taxable Amount")
    assert is_summary_line_description("Taxable Value 1000.00")
    assert is_summary_line_description("CESS")
    assert is_summary_line_description("Freight Total")
    assert is_summary_line_description("Discount Total 25.00")
    assert is_metadata_line_description("Name")
    assert not is_summary_line_description("GST consulting services")
    assert not is_summary_line_description("Widget assembly")
    assert not is_summary_line_description("Sandisk 4TB SSD")
    assert not is_summary_line_description("Total GST consulting services")


def test_metadata_labels_skipped() -> None:
    assert is_metadata_line_description("Customer:")
    assert is_metadata_line_description("Ship Date:")
    assert is_metadata_line_description("Invoice No:")
    assert is_metadata_line_description("Ship To: Acme Corp")
    assert is_metadata_line_description("Invoice Date: 01/01/2026")
    assert is_metadata_line_description("PO No: PO-123")
    assert is_metadata_line_description("Invoice Date 01/01/2026")
    assert is_metadata_line_description("Ship To Acme Corp Pty Ltd")
    assert is_metadata_line_description("Description Qty Unit Price Amount")
    assert is_metadata_line_description("Currency")
    assert is_metadata_line_description("Currency AUD")
    assert is_metadata_line_description("Cost Centre")
    assert is_metadata_line_description("Invoice Date")
    assert not is_metadata_line_description("Catering package")
    assert not is_metadata_line_description("Customer support package")


def test_bank_remittance_summary_skipped() -> None:
    assert should_skip_line_row("Bank Details: CBA")
    assert should_skip_line_row("Please remit to account")


def test_should_skip_line_row_combines_checks() -> None:
    assert should_skip_line_row("Sub Total")
    assert should_skip_line_row("Customer:")
    assert should_skip_line_row("Invoice Date: 12/03/2026")
    assert not should_skip_line_row("SEO Services")
