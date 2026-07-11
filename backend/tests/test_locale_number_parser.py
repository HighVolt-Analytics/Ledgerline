"""Tests for locale-aware decimal parsing."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.services.extraction.field_grounding_service import _normalize_money_for_grounding
from app.services.shared.locale_number_parser import _legacy_us_parse, parse_localized_decimal


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234.56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("1234", Decimal("1234")),
        ("1,234", Decimal("1234")),
        ("12.345.678,90", Decimal("12345678.90")),
    ],
)
def test_parse_localized_decimal_new_formats(raw: str, expected: Decimal) -> None:
    assert parse_localized_decimal(raw) == expected


GOLDEN_US_AMOUNTS = [
    "145.00",
    "11600.00",
    "SGD 500.00",
    "$2,450.00",
    "$245.00",
    "$2,695.00",
    "$380.00",
    "$1,234.56",
]


def test_parse_localized_decimal_matches_legacy_us_formats() -> None:
    for raw in GOLDEN_US_AMOUNTS:
        legacy = _legacy_us_parse(raw)
        assert legacy is not None, raw
        parsed = parse_localized_decimal(raw)
        assert parsed == legacy, f"mismatch for {raw!r}: {parsed} vs {legacy}"


def test_normalize_money_for_grounding_golden_us() -> None:
    for raw in ("$1,234.56", "145.00", "SGD 500.00"):
        legacy_cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
        legacy_norm = format(Decimal(legacy_cleaned).normalize(), "f").rstrip("0").rstrip(".")
        assert _normalize_money_for_grounding(raw) == legacy_norm


def test_locale_ambiguous_amount_logged(capsys: pytest.CaptureFixture[str]) -> None:
    result = parse_localized_decimal("12,345", log_context={"fixture": "ambiguous"})
    assert result == Decimal("12345")
    captured = capsys.readouterr().out
    assert "locale_ambiguous_amount" in captured
