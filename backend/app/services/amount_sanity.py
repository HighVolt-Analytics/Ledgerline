"""Reject OCR amounts that cannot fit invoice money columns."""

from __future__ import annotations

from decimal import Decimal

_MAX_MONEY = Decimal("9999999999.99")


def plausible_money(value: Decimal | None) -> Decimal | None:
    """Drop values that overflow NUMERIC(12,2) or look like ABNs / IDs."""
    if value is None:
        return None
    abs_value = value.copy_abs()
    if abs_value > _MAX_MONEY:
        return None
    if abs_value >= Decimal("10000000"):
        return None
    return value
