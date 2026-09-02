"""Dashboard period window resolution."""

from __future__ import annotations

from datetime import date

from app.services.reports.dashboard_period import (
    DEFAULT_DASHBOARD_PERIOD,
    fy_window,
    resolve_dashboard_period,
)


def test_fy_window_august_2026() -> None:
    """Aug 2026 is in Australian FY27 (Jul 2026 – Jun 2027)."""
    as_of = date(2026, 8, 31)
    start, end, label = fy_window(as_of)
    assert start == date(2026, 7, 1)
    assert end == as_of
    assert label == "FY27 YTD to 31 Aug 2026"


def test_fy_window_august_2025() -> None:
    """Aug 2025 is in Australian FY26 (Jul 2025 – Jun 2026)."""
    as_of = date(2025, 8, 31)
    start, end, label = fy_window(as_of)
    assert start == date(2025, 7, 1)
    assert end == as_of
    assert label == "FY26 YTD to 31 Aug 2025"


def test_fy_window_june_2026() -> None:
    """Jun 2026 is still FY26 (FY ends 30 Jun)."""
    as_of = date(2026, 6, 30)
    start, end, label = fy_window(as_of)
    assert start == date(2025, 7, 1)
    assert end == as_of
    assert label == "FY26 YTD to 30 Jun 2026"


def test_mtd_september_2026() -> None:
    as_of = date(2026, 9, 15)
    start, end, label = resolve_dashboard_period("mtd", as_of)
    assert start == date(2026, 9, 1)
    assert end == as_of
    assert label == "Sep 2026 MTD"


def test_fq_ytd_q1_august_in_fy27() -> None:
    as_of = date(2026, 8, 15)
    start, end, label = resolve_dashboard_period("fq_ytd", as_of)
    assert start == date(2026, 7, 1)
    assert end == as_of
    assert "FY27 Q1 YTD" in label


def test_fq_ytd_q1_october_counts_as_q2() -> None:
    as_of = date(2026, 10, 5)
    start, end, label = resolve_dashboard_period("fq_ytd", as_of)
    assert start == date(2026, 10, 1)
    assert end == as_of
    assert "FY27 Q2 YTD" in label


def test_r12_window() -> None:
    as_of = date(2026, 8, 31)
    start, end, _ = resolve_dashboard_period("r12", as_of)
    assert start == date(2025, 9, 1)
    assert end == as_of


def test_unknown_period_defaults_to_fy_ytd() -> None:
    as_of = date(2026, 8, 31)
    start, end, label = resolve_dashboard_period("invalid", as_of)
    expected_start, expected_end, expected_label = resolve_dashboard_period(
        DEFAULT_DASHBOARD_PERIOD, as_of
    )
    assert start == expected_start
    assert end == expected_end
    assert label == expected_label
