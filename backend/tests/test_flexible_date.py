"""Tests for flexible date parsing."""

from datetime import date

import pytest

from app.services.shared.flexible_date import parse_flexible_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04-20", date(2026, 4, 20)),
        ("15/03/2026", date(2026, 3, 15)),
        ("20 April 2026", date(2026, 4, 20)),
        ("April 20, 2026", date(2026, 4, 20)),
        ("Apr 20, 2026", date(2026, 4, 20)),
        ("Date of issue April 20, 2026", None),
    ],
)
def test_parse_flexible_date(raw: str, expected: date | None) -> None:
    assert parse_flexible_date(raw) == expected


def test_parse_flexible_date_us_order() -> None:
    assert parse_flexible_date("04/20/2026", date_order="MDY") == date(2026, 4, 20)


def test_parse_flexible_date_empty() -> None:
    assert parse_flexible_date("") is None
    assert parse_flexible_date(None) is None
