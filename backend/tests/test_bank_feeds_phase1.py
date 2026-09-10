"""Phase 1 bank-statement extraction: table/text merge, wraps, page-break stitch."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.bank_feeds.parse_common import (
    EXTRACTION_SOURCE_CONTINUATION_MERGE,
    EXTRACTION_SOURCE_TEXT_FALLBACK_MERGE,
    parse_statement_text_block,
)
from app.services.bank_feeds.pdf_parser import (
    _merge_table_and_text_results,
    _parse_table_rows,
    _parse_table_rows_raw,
    parse_bank_statement_pdf,
)


def test_table_text_coverage_merge_recovers_missed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """(a) synthetic: table misses a txn that text lines contain — merge recovers it."""
    # Table only has 2 of 3 transactions.
    partial_table = [
        ["Date", "Narration", "Withdrawals", "Deposits", "Balance"],
        ["01 Aug 2026", "Fuel", "25.04", "", "1000.00"],
        ["02 Aug 2026", "Refund", "", "50.00", "1050.00"],
    ]
    full_text = (
        "01 Aug 2026 Fuel 25.04 out 1000.00\n"
        "02 Aug 2026 Refund 50.00 in 1050.00\n"
        "03 Aug 2026 Pharmacy 10.00 out 1040.00\n"
        "04 Aug 2026 Streaming 5.00 out 1035.00\n"  # extra so date_like >> table (2)
        "05 Aug 2026 Utility 5.00 out 1030.00\n"
    )

    def _fake_extract(_path):
        return [partial_table], full_text

    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_pdf_tables_and_text",
        _fake_extract,
    )
    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_text_with_ocr_fallback",
        lambda _path, text, **_kwargs: (text, "pdfplumber"),
    )

    result = parse_bank_statement_pdf(b"%PDF-1.4 test")
    assert result.parse_meta.get("text_fallback_merge") == "true"
    assert int(result.parse_meta.get("text_fallback_merge_added", "0")) >= 1
    descs = {r.description for r in result.rows}
    assert any("Fuel" in d for d in descs)
    assert any("Pharmacy" in d for d in descs)
    # Table-derived Fuel must not be duplicated.
    fuel_rows = [r for r in result.rows if "Fuel" in r.description]
    assert len(fuel_rows) == 1
    recovered = [r for r in result.rows if r.extraction_source == EXTRACTION_SOURCE_TEXT_FALLBACK_MERGE]
    assert recovered
    # Direction confidence still from Phase 0 logic — not forced low by merge.
    assert all(r.direction_confidence != "low" or r.direction for r in recovered)


def test_wrapped_description_merged_in_table() -> None:
    """(b) synthetic: multi-line description continuation merges into one row."""
    table = [
        ["Date", "Narration", "Withdrawals", "Deposits", "Balance"],
        ["01 Aug 2026", "Payment to Acme", "100.00", "", "900.00"],
        ["", "Corp Invoice 4421-B", "", "", ""],
        ["02 Aug 2026", "Salary", "", "500.00", "1400.00"],
    ]
    parsed = _parse_table_rows(table)
    assert len(parsed.rows) == 2
    assert "Corp Invoice 4421-B" in parsed.rows[0].description
    assert parsed.rows[0].extraction_source == EXTRACTION_SOURCE_CONTINUATION_MERGE
    assert parsed.rows[0].amount == Decimal("100.00")
    assert parsed.rows[1].description == "Salary"


def test_wrapped_description_merged_in_text_block() -> None:
    text = (
        "01 Aug 2026 Payment to Acme 100.00 out 900.00\n"
        "Corp Invoice 4421-B\n"
        "02 Aug 2026 Salary 500.00 in 1400.00\n"
    )
    result = parse_statement_text_block(text)
    assert len(result.rows) == 2
    assert "Corp Invoice 4421-B" in result.rows[0].description
    assert result.rows[0].extraction_source == EXTRACTION_SOURCE_CONTINUATION_MERGE


def test_page_break_mid_transaction_stitched() -> None:
    """(c) synthetic: description split across two page tables is stitched."""
    page1 = [
        ["Date", "Narration", "Amount", "Balance"],
        # No balance → incomplete closing signal for cross-page stitch.
        ["01 Aug 2026", "Wire to Orion Systems for", "250.00", ""],
    ]
    page2 = [
        ["Date", "Narration", "Amount", "Balance"],
        ["", "project milestone 3", "", ""],
        ["02 Aug 2026", "Interest", "10.00", "760.00"],
    ]
    rows1, _, _, _ = _parse_table_rows_raw(page1)
    assert len(rows1) == 1
    assert rows1[0].balance is None

    previous = list(rows1)
    rows2, _, _, _ = _parse_table_rows_raw(
        page2,
        previous_rows=previous,
        require_incomplete_for_cross_table_stitch=True,
    )
    assert "project milestone 3" in previous[0].description
    assert previous[0].extraction_source == EXTRACTION_SOURCE_CONTINUATION_MERGE
    assert len(rows2) == 1
    assert rows2[0].description == "Interest"


def test_boilerplate_not_merged_as_continuation() -> None:
    table = [
        ["Date", "Narration", "Withdrawals", "Deposits", "Balance"],
        ["01 Aug 2026", "Fuel", "25.04", "", "1000.00"],
        ["", "Continued on next page", "", "", ""],
        ["02 Aug 2026", "Refund", "", "50.00", "1050.00"],
    ]
    parsed = _parse_table_rows(table)
    assert len(parsed.rows) == 2
    assert "Continued" not in parsed.rows[0].description


def test_merge_table_wins_on_fingerprint_conflict() -> None:
    from app.services.bank_feeds.parse_common import (
        CsvParseResult,
        DIRECTION_CONFIDENCE_HIGH,
        ParsedBankCsvRow,
    )

    table_row = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "debit",
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    # Same identity from text, plus a novel row.
    text_same = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "debit",
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    text_extra = ParsedBankCsvRow(
        2,
        date(2026, 8, 3),
        "Pharmacy",
        Decimal("10.00"),
        "debit",
        Decimal("990.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    merged = _merge_table_and_text_results(
        CsvParseResult(rows=[table_row], errors=[], extracted_count=1),
        CsvParseResult(rows=[text_same, text_extra], errors=[], extracted_count=2),
    )
    assert len(merged.rows) == 2
    assert merged.rows[0].extraction_source is None  # table wins, untouched
    assert merged.rows[1].extraction_source == EXTRACTION_SOURCE_TEXT_FALLBACK_MERGE
    assert merged.rows[1].direction_confidence == DIRECTION_CONFIDENCE_HIGH


def test_merge_direction_conflict_keeps_one_row_prefers_higher_confidence() -> None:
    """Addendum Step 1/2: same date/amount/desc, different direction → one row."""
    from app.services.bank_feeds.parse_common import (
        CsvParseResult,
        DIRECTION_CONFIDENCE_HIGH,
        DIRECTION_CONFIDENCE_MEDIUM,
        DIRECTION_DISAGREEMENT_NOTE,
        ParsedBankCsvRow,
    )
    from app.services.bank_feeds.pdf_parser import _txn_fingerprint

    table_row = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "debit",
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    text_row = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "credit",  # disagrees
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_MEDIUM,
    )
    # Step 1 baseline (documented): full fingerprints differ.
    assert _txn_fingerprint(table_row) != _txn_fingerprint(text_row)

    merged = _merge_table_and_text_results(
        CsvParseResult(rows=[table_row], errors=[], extracted_count=1),
        CsvParseResult(rows=[text_row], errors=[], extracted_count=1),
    )
    assert len(merged.rows) == 1
    assert merged.rows[0].direction == "debit"  # high > medium
    assert merged.rows[0].direction_confidence == DIRECTION_CONFIDENCE_HIGH
    assert merged.rows[0].extraction_note is None
    assert merged.parse_meta.get("text_fallback_merge_added") == "0"


def test_merge_direction_conflict_same_confidence_flags_low() -> None:
    from app.services.bank_feeds.parse_common import (
        CsvParseResult,
        DIRECTION_CONFIDENCE_HIGH,
        DIRECTION_DISAGREEMENT_NOTE,
        EXTRACTION_CONFIDENCE_LOW,
        ParsedBankCsvRow,
    )

    table_row = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "debit",
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    text_row = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "credit",
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    merged = _merge_table_and_text_results(
        CsvParseResult(rows=[table_row], errors=[], extracted_count=1),
        CsvParseResult(rows=[text_row], errors=[], extracted_count=1),
    )
    assert len(merged.rows) == 1
    assert merged.rows[0].direction == "debit"  # table wins tie
    assert merged.rows[0].extraction_confidence == EXTRACTION_CONFIDENCE_LOW
    assert merged.rows[0].extraction_note == DIRECTION_DISAGREEMENT_NOTE


def test_merge_direction_agree_unchanged() -> None:
    """When table and text agree on direction, still one row and no low flag."""
    from app.services.bank_feeds.parse_common import (
        CsvParseResult,
        DIRECTION_CONFIDENCE_HIGH,
        ParsedBankCsvRow,
    )

    table_row = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "debit",
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    text_row = ParsedBankCsvRow(
        1,
        date(2026, 8, 1),
        "Fuel Station",
        Decimal("25.04"),
        "debit",
        Decimal("1000.00"),
        None,
        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
    )
    merged = _merge_table_and_text_results(
        CsvParseResult(rows=[table_row], errors=[], extracted_count=1),
        CsvParseResult(rows=[text_row], errors=[], extracted_count=1),
    )
    assert len(merged.rows) == 1
    assert merged.rows[0].direction == "debit"
    assert merged.rows[0].extraction_source is None
    assert merged.rows[0].extraction_confidence is None
    assert merged.rows[0].extraction_note is None
