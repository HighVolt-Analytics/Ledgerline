"""Shared line-item skip patterns for parser, sanitizer, and frontend parity."""

from __future__ import annotations

import re

_ABN_ROW = re.compile(r"\babn\b", re.I)

# Metadata field labels that must never appear as product line rows.
_METADATA_LABEL = re.compile(
    r"^(?:"
    r"customer|ship(?:ped)?\s*(?:to|date|qty|ped)?|delivery\s*date|invoice\s*(?:no|number|#)|"
    r"po\s*(?:no|number|reference)?|order\s*(?:no|number)?|so\s*reference|"
    r"bill(?:ed)?\s*to|ship\s*to|vendor|supplier|abn|gstin|bsb|account\s*(?:no|number)?|"
    r"payment\s*terms|due\s*date|date\s*paid|receipt\s*(?:no|number)?|"
    r"phone|tel(?:ephone)?|mobile|email|fax|address|attn|attention"
    r")\s*:?\s*$",
    re.I,
)

_TABLE_HEADER = re.compile(
    r"^(?:description|item|product|qty|quantity|unit\s*price|amount|rate|uom|sku)\s*:?\s*$",
    re.I,
)


def is_summary_line_description(desc: str | None) -> bool:
    """True when description is a totals/summary row, not a product line."""
    text = re.sub(r"\s+", " ", (desc or "").strip())
    if not text:
        return True
    if re.search(r"sub\s*total|gst|total\s*due|amount\s*due", text, re.I):
        return True
    if re.search(
        r"\b(?:total\s+no\.?\s+of\s+pallet|no\.?\s+of\s+pallet|pallet\s*:)\b",
        text,
        re.I,
    ):
        return True
    if re.search(r"^total\b", text, re.I):
        return True
    if _ABN_ROW.search(text):
        return True
    return False


def is_metadata_line_description(desc: str | None) -> bool:
    """True when description is a header/metadata label, not a product line."""
    text = re.sub(r"\s+", " ", (desc or "").strip())
    if not text:
        return True
    if text.endswith(":") and len(text) <= 40:
        return True
    if _METADATA_LABEL.match(text):
        return True
    if _TABLE_HEADER.match(text):
        return True
    return False


def should_skip_line_row(desc: str | None) -> bool:
    """Combined skip check used by parser and sanitizer."""
    return is_summary_line_description(desc) or is_metadata_line_description(desc)
