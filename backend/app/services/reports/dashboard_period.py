"""Dashboard reporting windows — Australian FY calendar (Jul–Jun)."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal

DashboardPeriod = Literal["fy_ytd", "mtd", "fq_ytd", "r12"]

DEFAULT_DASHBOARD_PERIOD: DashboardPeriod = "fy_ytd"
VALID_DASHBOARD_PERIODS: frozenset[str] = frozenset({"fy_ytd", "mtd", "fq_ytd", "r12"})

_MONTH_NAMES = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _fy_start_year(as_of: date) -> int:
    return as_of.year if as_of.month >= 7 else as_of.year - 1


def _fy_end_year(as_of: date) -> int:
    return _fy_start_year(as_of) + 1


def _fy_label(as_of: date) -> str:
    return f"FY{str(_fy_end_year(as_of))[-2:]}"


def _subtract_months(value: date, months: int) -> date:
    year = value.year
    month = value.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def fy_window(as_of: date) -> tuple[date, date, str]:
    """Financial year YTD: 1 Jul → as_of (Australian FY)."""
    start_year = _fy_start_year(as_of)
    start = date(start_year, 7, 1)
    label = (
        f"{_fy_label(as_of)} YTD to "
        f"{as_of.day} {_MONTH_NAMES[as_of.month]} {as_of.year}"
    )
    return start, as_of, label


def resolve_dashboard_period(
    period: str | None,
    as_of: date,
) -> tuple[date, date, str]:
    key = period if period in VALID_DASHBOARD_PERIODS else DEFAULT_DASHBOARD_PERIOD

    if key == "fy_ytd":
        return fy_window(as_of)

    if key == "mtd":
        start = date(as_of.year, as_of.month, 1)
        label = f"{_MONTH_NAMES[as_of.month]} {as_of.year} MTD"
        return start, as_of, label

    if key == "fq_ytd":
        fy_start_year = _fy_start_year(as_of)
        month = as_of.month
        if month >= 7:
            if month <= 9:
                quarter = "Q1"
                start = date(fy_start_year, 7, 1)
            else:
                quarter = "Q2"
                start = date(fy_start_year, 10, 1)
        elif month <= 3:
            quarter = "Q3"
            start = date(fy_start_year + 1, 1, 1)
        else:
            quarter = "Q4"
            start = date(fy_start_year + 1, 4, 1)
        label = (
            f"{_fy_label(as_of)} {quarter} YTD to "
            f"{as_of.day} {_MONTH_NAMES[as_of.month]} {as_of.year}"
        )
        return start, as_of, label

    # r12 — rolling 12 months ending as_of (inclusive)
    anchor = _subtract_months(as_of, 12)
    start = anchor + timedelta(days=1)
    label = f"Rolling 12 months to {as_of.day} {_MONTH_NAMES[as_of.month]} {as_of.year}"
    return start, as_of, label
