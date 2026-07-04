"""Locale-flexible date parsing for document extraction."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

DateOrder = Literal["DMY", "MDY", "YMD"]

_NUMERIC_FORMATS_DMY: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
)

_NUMERIC_FORMATS_MDY: tuple[str, ...] = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%m.%d.%Y",
)

_NAME_FORMATS: tuple[str, ...] = (
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%b %d,%Y",
    "%B %d,%Y",
)


def _clean_date_token(raw: str) -> str:
    token = (raw or "").strip()
    token = re.sub(r"\s+", " ", token)
    token = token.rstrip(".,;")
    return token.strip()


def parse_flexible_date(
    raw: str | None,
    *,
    date_order: DateOrder = "DMY",
) -> date | None:
    """Parse common invoice date strings (AU, US, ISO, month names)."""
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()

    token = _clean_date_token(str(raw))
    if not token:
        return None

    numeric = _NUMERIC_FORMATS_MDY if date_order == "MDY" else _NUMERIC_FORMATS_DMY
    if date_order == "YMD":
        numeric = ("%Y-%m-%d", "%Y/%m/%d")

    for fmt in (*numeric, *_NAME_FORMATS):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue

    # Ambiguous slash dates: try alternate order when first pass fails.
    if date_order == "DMY" and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", token):
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                continue
    if date_order == "MDY" and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", token):
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                continue

    return None
