"""Shared sanitization for short reference columns (SO, PO, cost centre)."""

from __future__ import annotations

from collections.abc import Callable

_REFERENCE_LIKE_KEYS = frozenset(
    {
        "so_reference",
        "po_reference",
        "cost_centre",
        "sales_order",
        "sales_order_no",
        "so_number",
    }
)


def has_multiline_text(value: str | None) -> bool:
    if not value:
        return False
    return "\n" in value or "\r" in value


def sanitize_reference_value(value: object | None, *, max_len: int = 100) -> str | None:
    """Strip and cap reference text; reject multiline blobs."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if has_multiline_text(text):
        return None
    if len(text) > max_len:
        text = text[:max_len].strip()
    return text or None


def sanitize_reference_for_column(
    value: object | None,
    *,
    max_len: int = 100,
    is_plausible: Callable[[str], bool] | None = None,
) -> str | None:
    """Return a DB-safe reference value or None when implausible."""
    cleaned = sanitize_reference_value(value, max_len=max_len)
    if not cleaned:
        return None
    if is_plausible is not None and not is_plausible(cleaned):
        return None
    return cleaned


def is_reference_like_extraction_key(key: str) -> bool:
    return str(key or "").strip().lower() in _REFERENCE_LIKE_KEYS
