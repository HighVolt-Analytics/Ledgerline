"""Balance-marker row classification — opening/closing B/F without amounts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.bank_feeds.parse_common import (
    STATED_OPENING_MISMATCH_MSG,
    STATED_OPENING_MISMATCH_NOTE,
    is_balance_marker_description,
)
from app.services.bank_feeds.pdf_parser import _parse_table_rows
from app.services.bank_feeds.statement_parse_profile import GENERIC_V1


def test_opening_closing_markers_excluded_and_captured() -> None:
    table = [
        ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
        ["01/08/2026", "OPENING BALANCE", "", "", "500,000.00"],
        ["02/08/2026", "Salary Credit", "", "10,000.00", "510,000.00"],
        ["05/08/2026", "Rent Payment", "2,000.00", "", "508,000.00"],
        ["31/08/2026", "CLOSING BALANCE", "", "", "508,000.00"],
    ]
    result = _parse_table_rows(table, profile=GENERIC_V1)
    assert result.errors == [], [e.message for e in result.errors]
    assert len(result.rows) == 2
    assert result.rows[0].description == "Salary Credit"
    assert result.rows[1].description == "Rent Payment"
    assert result.parse_meta.get("stated_opening_balance") == "500000.00"
    assert result.parse_meta.get("stated_closing_balance") == "508000.00"
    assert result.skipped_line_count == 2


def test_stated_opening_mismatch_flags_continuity() -> None:
    # Stated opening 500k, but first txn balance implies opening was 400k.
    table = [
        ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
        ["01/08/2026", "OPENING BALANCE", "", "", "500,000.00"],
        ["02/08/2026", "Salary Credit", "", "10,000.00", "410,000.00"],
        ["31/08/2026", "CLOSING BALANCE", "", "", "410,000.00"],
    ]
    result = _parse_table_rows(table, profile=GENERIC_V1)
    assert len(result.rows) == 1
    assert any(STATED_OPENING_MISMATCH_MSG in e.message for e in result.errors)
    assert result.rows[0].extraction_confidence == "low"
    assert result.rows[0].extraction_note == STATED_OPENING_MISMATCH_NOTE
    assert result.parse_meta.get("stated_opening_balance") == "500000.00"


def test_balance_transfer_fee_with_amount_not_excluded() -> None:
    table = [
        ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
        ["01/08/2026", "OPENING BALANCE", "", "", "1,000.00"],
        ["03/08/2026", "BALANCE TRANSFER FEE", "150.00", "", "850.00"],
        ["31/08/2026", "CLOSING BALANCE", "", "", "850.00"],
    ]
    result = _parse_table_rows(table, profile=GENERIC_V1)
    assert len(result.rows) == 1
    assert result.rows[0].description == "BALANCE TRANSFER FEE"
    assert result.rows[0].amount == Decimal("150.00")
    assert result.rows[0].direction == "debit"
    assert result.rows[0].txn_date == date(2026, 8, 3)
    assert not is_balance_marker_description("BALANCE TRANSFER FEE")
    # Opening 1000, first debit 150 → balance 850 ⇒ inferred opening 1000 — match.
    assert result.errors == []
    assert result.parse_meta.get("stated_opening_balance") == "1000.00"
    assert result.parse_meta.get("stated_closing_balance") == "850.00"


def test_profile_exposes_balance_marker_phrases() -> None:
    assert "opening balance" in GENERIC_V1.balance_marker_phrases
    assert "balance b/f" in GENERIC_V1.balance_marker_phrases
    assert is_balance_marker_description("Balance B/F")
    assert is_balance_marker_description("Opening Bal.")
