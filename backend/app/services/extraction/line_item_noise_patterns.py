"""Configurable noise heuristics for line-item rows from loose OCR text."""

from __future__ import annotations

import re
from decimal import Decimal

ADDRESS_LIKE = re.compile(
    r"\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|drive|dr\.?|lane|ln\.?|boulevard|blvd\.?|"
    r"henderson|singapore|postal|zip\s*code)\b",
    re.I,
)
POSTAL_RUN = re.compile(r"\b\d{4,6}\b")

REFERENCE_BLOCK = re.compile(
    r"\b(?:DOCUMENTARY\s+CREDIT|CERTIFICATE|REFERENCE\s+NO|CONTRACT\s+NO|IRC\s+NO|TIN\b|BIN\s+NO)\b",
    re.I,
)

BARE_CODE_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9\-/_]{1,20}$", re.I)


def is_noise_line_item_row(description: str | None, qty: Decimal | None = None) -> bool:
    """True when a row looks like address/reference/metadata rather than a product line."""
    desc = (description or "").strip()
    if not desc:
        return True
    if REFERENCE_BLOCK.search(desc):
        return True
    if ADDRESS_LIKE.search(desc) and POSTAL_RUN.search(desc):
        return True
    if ADDRESS_LIKE.search(desc) and len(desc.split()) <= 8:
        return True
    if BARE_CODE_TOKEN.match(desc) and qty is not None and qty > Decimal("10000"):
        return True
    words = [word for word in re.split(r"\s+", desc) if word]
    if len(words) <= 3 and qty is not None and qty > Decimal("1000"):
        if not re.search(r"\b(?:cpu|chip|part|widget|item|unit|kg|pcs)\b", desc, re.I):
            return True
    return False
