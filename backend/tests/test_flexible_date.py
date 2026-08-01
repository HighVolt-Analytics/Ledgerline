"""Tests for flexible date parsing."""

from datetime import date

import pytest

from app.services.shared.flexible_date import (
    date_ocr_match_tokens,
    parse_flexible_date,
    recover_labeled_invoice_date_from_text,
    strip_date_label_prefix,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04-20", date(2026, 4, 20)),
        ("2026-04-20T00:00:00", date(2026, 4, 20)),
        ("2026-04-20T14:30:00Z", date(2026, 4, 20)),
        ("20250905", date(2025, 9, 5)),
        ("15/03/2026", date(2026, 3, 15)),
        ("2026/03/15", date(2026, 3, 15)),
        ("05-Sep-2025", date(2025, 9, 5)),
        ("15-Mar-2026", date(2026, 3, 15)),
        ("20 April 2026", date(2026, 4, 20)),
        ("April 20, 2026", date(2026, 4, 20)),
        ("Apr 20, 2026", date(2026, 4, 20)),
        ("Date of issue April 20, 2026", date(2026, 4, 20)),
        ("4/9/2025", date(2025, 9, 4)),
    ],
)
def test_parse_flexible_date(raw: str, expected: date | None) -> None:
    assert parse_flexible_date(raw) == expected


def test_parse_flexible_date_us_order() -> None:
    assert parse_flexible_date("04/20/2026", date_order="MDY") == date(2026, 4, 20)
    assert parse_flexible_date("4/9/2025", date_order="MDY") == date(2025, 4, 9)


def test_parse_flexible_date_empty() -> None:
    assert parse_flexible_date("") is None
    assert parse_flexible_date(None) is None


def test_strip_date_label_prefix() -> None:
    assert strip_date_label_prefix("Invoice Date: 15/03/2026") == "15/03/2026"


def test_date_ocr_match_tokens_includes_unpadded_slash_date() -> None:
    tokens = date_ocr_match_tokens(date(2025, 4, 9))
    assert "4/9/2025" in tokens
    assert "04/09/2025" in tokens


def test_date_ocr_match_tokens_includes_unpadded_month_name() -> None:
    tokens = date_ocr_match_tokens(date(2026, 6, 3))
    assert "3 June 2026" in tokens
    assert "03 June 2026" in tokens


def test_recover_labeled_invoice_date_from_text() -> None:
    text = (
        "COMMERCIAL INVOICE\n"
        "Invoice Date: 4/9/2025\n"
        "Due Date: 30/09/2025\n"
        + ("padding " * 20)
    )
    assert recover_labeled_invoice_date_from_text(text) == date(2025, 9, 4)


def test_recover_claim_form_header_date_column() -> None:
    text = (
        "EMPLOYEE EXPENSE CLAIM FORM\n"
        "CLAIM NO. DATE\n"
        "EXP-2026-091 3 June 2026\n"
        "EMPLOYEE NAME\n"
        "Vishnu\n"
    )
    assert recover_labeled_invoice_date_from_text(text) == date(2026, 6, 3)


def test_recover_labeled_invoice_date_skips_validity_label() -> None:
    text = "VALIDITY PERIOD : 05/09/2025\n" + ("padding " * 20)
    assert recover_labeled_invoice_date_from_text(text) is None
