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
    assert not is_summary_line_description("GST consulting services")
    assert not is_summary_line_description("Widget assembly")
    assert not is_summary_line_description("Sandisk 4TB SSD")


def test_metadata_labels_skipped() -> None:
    assert is_metadata_line_description("Customer:")
    assert is_metadata_line_description("Ship Date:")
    assert is_metadata_line_description("Invoice No:")
    assert not is_metadata_line_description("Catering package")


def test_should_skip_line_row_combines_checks() -> None:
    assert should_skip_line_row("Sub Total")
    assert should_skip_line_row("Customer:")
    assert not should_skip_line_row("SEO Services")
