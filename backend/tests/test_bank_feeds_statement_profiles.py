"""Phase 2 statement parse profiles — generic regression + custom profile fixtures."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.bank_feeds.parse_common import (
    MoneyFormat,
    parse_money_token,
    parse_statement_date,
    parse_statement_text_block,
)
from app.services.bank_feeds.pdf_parser import _parse_table_rows, parse_bank_statement_pdf
from app.services.bank_feeds.statement_parse_profile import (
    EU_DECIMAL_V1,
    GENERIC_V1,
    INDIAN_NARRATION_V1,
    US_MDY_V1,
    StatementParseProfileError,
    load_statement_parse_profile,
    validate_profile_dict,
)


def test_generic_v1_is_default_and_loads() -> None:
    assert load_statement_parse_profile(None).profile_id == "generic_v1"
    assert load_statement_parse_profile("").profile_id == "generic_v1"
    assert load_statement_parse_profile("generic_v1") is GENERIC_V1


def test_unknown_profile_id_raises_clear_error() -> None:
    with pytest.raises(StatementParseProfileError, match="Unknown statement parse profile"):
        load_statement_parse_profile("does_not_exist")


def test_malformed_profile_rejected_not_silent_fallback() -> None:
    with pytest.raises(StatementParseProfileError, match="profile_id"):
        validate_profile_dict({"locale": "en"})
    with pytest.raises(StatementParseProfileError, match="decimal_separator"):
        validate_profile_dict(
            {
                "profile_id": "bad",
                "decimal_separator": "..",
                "header_aliases": {k: list(v) for k, v in GENERIC_V1.header_aliases.items()},
            }
        )


def test_eu_decimal_profile_parses_european_amounts() -> None:
    """generic_v1 misreads EU money; eu_decimal_v1 succeeds."""
    raw = "1.234,56"
    # Generic path strips commas only → Decimal("1.23456"), not 1234.56.
    wrong, _ = parse_money_token(raw)
    assert wrong != Decimal("1234.56")

    amount, direction = parse_money_token(
        raw, money_format=MoneyFormat.from_profile(EU_DECIMAL_V1)
    )
    assert amount == Decimal("1234.56")
    assert direction is None

    from app.services.bank_feeds.parse_common import DocumentDateOrder

    trailing = "01/02/2024 Payment 1.234,56- 5.000,00"
    eu = parse_statement_text_block(
        trailing,
        money_format=MoneyFormat.from_profile(EU_DECIMAL_V1),
        date_order=DocumentDateOrder(order="dmy", assumed=False),
        refine_direction_mode=EU_DECIMAL_V1.refine_direction_mode,
    )
    assert len(eu.rows) == 1
    assert eu.rows[0].amount == Decimal("1234.56")
    assert eu.rows[0].direction == "debit"
    assert eu.rows[0].balance == Decimal("5000.00")
    assert eu.rows[0].txn_date == date(2024, 2, 1)


def test_us_mdy_profile_fixes_ambiguous_dates() -> None:
    """Ambiguous 01/02/2024: generic auto+DMY → 1 Feb; us_mdy_v1 → 2 Jan."""
    text = (
        "01/02/2024 Coffee 10.00 out 90.00\n"
        "03/04/2024 Lunch 5.00 out 85.00\n"
    )
    generic = parse_statement_text_block(text)  # auto → assumed dmy
    assert generic.rows[0].txn_date == date(2024, 2, 1)

    from app.services.bank_feeds.parse_common import DocumentDateOrder

    us = parse_statement_text_block(
        text,
        date_order=DocumentDateOrder(order="mdy", assumed=False),
    )
    assert us.rows[0].txn_date == date(2024, 1, 2)
    assert us.rows[1].txn_date == date(2024, 3, 4)
    assert parse_statement_date("01/02/2024", date_order="mdy") == date(2024, 1, 2)


def test_indian_narration_headers_need_custom_aliases() -> None:
    """Value Dt / Withdrawal Amt headers: generic misses mapping; custom profile maps."""
    table = [
        ["Value Dt", "Narration", "Withdrawal Amt", "Deposit Amt", "Balance"],
        ["01 Aug 2026", "UPI Cafe", "640.00", "", "591360.00"],
        ["02 Aug 2026", "Salary", "", "1000.00", "592360.00"],
    ]
    generic_parsed = _parse_table_rows(table, profile=GENERIC_V1)
    # Without "value dt" / "withdrawal amt", header map fails → heuristic may still
    # recover, but assert custom profile explicitly maps headers.
    custom = _parse_table_rows(table, profile=INDIAN_NARRATION_V1)
    assert len(custom.rows) == 2
    assert custom.rows[0].direction == "debit"
    assert custom.rows[0].amount == Decimal("640.00")
    assert custom.rows[1].direction == "credit"
    assert custom.parse_meta.get("column_strategy") == "headers"

    # Prove generic aliases alone do not recognize "Value Dt" as date via exact map.
    from app.services.bank_feeds.pdf_parser import _map_table_headers

    assert _map_table_headers(table[0], aliases=dict(GENERIC_V1.header_aliases)) is None
    assert (
        _map_table_headers(table[0], aliases=dict(INDIAN_NARRATION_V1.header_aliases))
        is not None
    )


def test_pdf_entry_honours_profile_id_in_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    table = [
        ["Date", "Narration", "Withdrawals", "Deposits", "Balance"],
        ["01 Aug 2026", "Fuel", "25.04", "", "1000.00"],
    ]

    def _fake_extract(_path):
        return [table], "01 Aug 2026 Fuel 25.04 out 1000.00\n"

    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_pdf_tables_and_text",
        _fake_extract,
    )
    monkeypatch.setattr(
        "app.services.bank_feeds.pdf_parser._extract_text_with_ocr_fallback",
        lambda path, local_text, **kwargs: (local_text, "pdfplumber"),
    )

    result = parse_bank_statement_pdf(b"%PDF-1.4 x", profile=US_MDY_V1)
    assert result.parse_meta.get("parse_profile_id") == "us_mdy_v1"
    assert len(result.rows) == 1
