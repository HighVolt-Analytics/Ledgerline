"""Track 2 — coverage-gap false trigger + blank-balance continuity carry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.bank_feeds.parse_common import (
    BALANCE_CONTINUITY_MSG,
    ParsedBankCsvRow,
    validate_balance_continuity,
)
from app.services.bank_feeds.pdf_parser import (
    _count_date_like_lines,
    _parse_table_rows,
    parse_bank_statement_pdf,
)
from app.services.bank_feeds.statement_parse_profile import GENERIC_V1


def test_finding_a_clean_table_with_header_markers_no_coverage_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean header table + dated OPENING/CLOSING lines must not trip coverage-gap."""
    table = [
        ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
        ["01/01/2027", "OPENING BALANCE", "", "", "100,000.00"],
        ["02/01/2027", "POS PURCHASE - CITY MART", "1,250.00", "", "98,750.00"],
        ["03/01/2027", "TRANSFER IN - J DOE", "", "8,000.00", "106,750.00"],
        ["04/01/2027", "BANK FEE", "100.00", "", "106,650.00"],
        ["05/01/2027", "SALARY CREDIT", "", "50,000.00", "156,650.00"],
        ["06/01/2027", "RENT PAYMENT", "2,000.00", "", "154,650.00"],
        ["31/01/2027", "CLOSING BALANCE", "", "", "154,650.00"],
    ]
    text_lines = [
        "SUMMIT NATIONAL BANK",
        "Statement Period: 01/01/2027 - 31/01/2027",
        "01/01/2027 OPENING BALANCE 100,000.00",
        "02/01/2027 POS PURCHASE - CITY MART 1,250.00 98,750.00",
        "03/01/2027 TRANSFER IN - J DOE 8,000.00 106,750.00",
        "04/01/2027 BANK FEE 100.00 106,650.00",
        "05/01/2027 SALARY CREDIT 50,000.00 156,650.00",
        "06/01/2027 RENT PAYMENT 2,000.00 154,650.00",
        "31/01/2027 CLOSING BALANCE 154,650.00",
        "Page 1 of 1",
    ]
    text = "\n".join(text_lines)

    # Reproduce pre-fix inflation: raw DATE_PREFIX count includes markers.
    raw_date_prefix = sum(
        1
        for line in text_lines
        if __import__("re").match(
            r"^(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", line
        )
    )
    assert raw_date_prefix == 7  # 5 txns + opening + closing
    txn_date_like = _count_date_like_lines(
        text, balance_marker_phrases=tuple(GENERIC_V1.balance_marker_phrases)
    )
    table_only = _parse_table_rows(table)
    assert len(table_only.rows) == 5
    assert table_only.errors == []
    # Pre-fix trigger: 7 > 5*1.2=6.0 — would have merged. Post-fix: 5 > 6.0 is false.
    assert raw_date_prefix > len(table_only.rows) * 1.2
    assert txn_date_like == 5
    assert not (txn_date_like > len(table_only.rows) * 1.2)

    def _fake_extract(_path):
        return [table], text

    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_pdf_tables_and_text",
        _fake_extract,
    )
    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_text_with_ocr_fallback",
        lambda _path, local_text, **_kwargs: (local_text, "pdfplumber"),
    )

    result = parse_bank_statement_pdf(b"%PDF-1.4 clean-table")
    assert result.parse_meta.get("text_fallback_merge") != "true"
    assert result.errors == [], [e.message for e in result.errors]
    assert len(result.rows) == 5
    assert all(r.direction in {"debit", "credit"} for r in result.rows)


def test_finding_b_blank_balance_amount_carries_into_next_continuity() -> None:
    """Blank-balance row stays in the list; its amount applies to the next checkpoint."""
    rows = [
        ParsedBankCsvRow(
            1,
            date(2027, 1, 1),
            "SALARY",
            Decimal("10000"),
            "credit",
            Decimal("70000.00"),
            None,
            direction_confidence="high",
        ),
        ParsedBankCsvRow(
            2,
            date(2027, 1, 2),
            "WIRE TO VENDOR (no balance printed)",
            Decimal("6200"),
            "debit",
            None,  # intentionally blank
            None,
            direction_confidence="high",
        ),
        ParsedBankCsvRow(
            3,
            date(2027, 1, 3),
            "ATM WITHDRAWAL",
            Decimal("2000"),
            "debit",
            Decimal("61800.00"),  # 70000 - 6200 - 2000
            None,
            direction_confidence="high",
        ),
    ]
    errors = validate_balance_continuity(rows)
    assert errors == [], [e.message for e in errors]

    # If intervening amount were ignored, expected would be 68000 and falsely flag.
    # Prove the old immediate-prev behavior would have been wrong when row is dropped:
    dropped = [rows[0], rows[2]]
    dropped_errors = validate_balance_continuity(dropped)
    assert len(dropped_errors) == 1
    assert BALANCE_CONTINUITY_MSG in dropped_errors[0].message


def test_finding_b_blank_balance_row_not_removed_from_table_parse() -> None:
    table = [
        ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
        ["01/01/2027", "SALARY", "", "10,000.00", "70,000.00"],
        ["02/01/2027", "WIRE TO VENDOR", "6,200.00", "", ""],
        ["03/01/2027", "ATM WITHDRAWAL", "2,000.00", "", "61,800.00"],
    ]
    result = _parse_table_rows(table)
    assert len(result.rows) == 3
    assert result.rows[1].balance is None
    assert result.rows[1].amount == Decimal("6200.00")
    assert result.errors == [] or not any(
        BALANCE_CONTINUITY_MSG in e.message for e in result.errors
    )
    assert result.errors == []
