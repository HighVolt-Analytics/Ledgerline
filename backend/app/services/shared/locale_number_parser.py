"""Locale-aware decimal parsing for OCR money tokens (US/UK and EU formats)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.utils.logger import get_logger

logger = get_logger(__name__)

_CURRENCY_NOISE = re.compile(r"[^\d,.\-]+")


def _legacy_us_parse(raw: str) -> Decimal | None:
    """Previous strip-commas US-only behavior (used in regression tests)."""
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_localized_decimal(
    raw: str,
    *,
    hint_locale: str | None = None,
    log_context: dict[str, str] | None = None,
) -> Decimal | None:
    """Parse a localized money string into Decimal.

    Heuristics:
    - When both '.' and ',' appear, the last separator followed by 1-2 digits at
      end-of-string is the decimal separator; the other is thousands.
    - Single separator: 3 digits after -> thousands; 1-2 digits after at EOL -> decimal.
    - Otherwise US-default (comma = thousands, dot = decimal).
    - Logs ``locale_ambiguous_amount`` when resolution is ambiguous.
    """
    token = (raw or "").strip()
    if not token:
        return None

    stripped = _CURRENCY_NOISE.sub("", token)
    if not stripped or stripped in {"-", "."}:
        return None

    has_dot = "." in stripped
    has_comma = "," in stripped
    ambiguous = False

    if has_dot and has_comma:
        last_dot = stripped.rfind(".")
        last_comma = stripped.rfind(",")
        if last_comma > last_dot:
            # EU: 1.234,56
            decimal_sep = ","
            thousands_sep = "."
        else:
            # US: 1,234.56
            decimal_sep = "."
            thousands_sep = ","
        body = stripped.replace(thousands_sep, "")
        if decimal_sep == ",":
            body = body.replace(",", ".")
        cleaned = body
    elif has_comma and not has_dot:
        comma_pos = stripped.rfind(",")
        after = stripped[comma_pos + 1 :]
        if len(after) in {1, 2} and after.isdigit():
            cleaned = stripped[:comma_pos].replace(",", "") + "." + after
        elif len(after) == 3 and after.isdigit():
            cleaned = stripped.replace(",", "")
            ambiguous = True
        else:
            cleaned = stripped.replace(",", "")
            ambiguous = True
    elif has_dot and not has_comma:
        dot_pos = stripped.rfind(".")
        after = stripped[dot_pos + 1 :]
        if len(after) == 3 and after.isdigit() and dot_pos > 0:
            # EU thousands: 12.345
            cleaned = stripped.replace(".", "")
            ambiguous = True
        else:
            cleaned = stripped
    else:
        cleaned = stripped

    if ambiguous:
        logger.info(
            "locale_ambiguous_amount",
            raw=raw,
            hint_locale=hint_locale or "",
            **(log_context or {}),
        )

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return _legacy_us_parse(raw)
