"""Regex helpers for tenant-defined extraction fields from OCR text."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.extraction.extraction_field_values import extraction_field_label

if TYPE_CHECKING:
    from collections.abc import Sequence

_MAX_VALUE_LEN = 500


def _label_variants(key: str) -> list[str]:
    label = extraction_field_label(key)
    variants = [label, key.replace("_", " "), key]
    seen: set[str] = set()
    out: list[str] = []
    for raw in variants:
        token = raw.strip()
        lowered = token.lower()
        if token and lowered not in seen:
            seen.add(lowered)
            out.append(token)
    return out


def _value_after_label_match(body: str, match: re.Match[str]) -> str:
    """Take same-line value, or the next non-empty line when labels are newline-KV."""
    same_line = (match.group(1) or "").strip().splitlines()[0].strip()
    if same_line:
        return same_line[:_MAX_VALUE_LEN]
    tail = body[match.end() :]
    for line in tail.splitlines():
        token = line.strip()
        if token:
            return token[:_MAX_VALUE_LEN]
    return ""


def extract_label_value_fields_from_text(
    text: str | None,
    keys: Sequence[str],
) -> dict[str, str]:
    """Best-effort label: value extraction for configured field keys.

    Supports ``Label: value``, ``Label - value``, and newline forms:
    ``Label\\nvalue`` (common in Azure layout OCR).
    """
    if not text or not str(text).strip() or not keys:
        return {}
    body = str(text)
    found: dict[str, str] = {}
    for raw_key in keys:
        key = str(raw_key or "").strip().lower()
        if not key or key in found:
            continue
        for label in _label_variants(key):
            # Optional delimiter; capture rest of line (may be empty for newline KV).
            pattern = re.compile(
                rf"(?im)^[ \t]*{re.escape(label)}\s*[:\-]?\s*(.*)$"
            )
            match = pattern.search(body)
            if not match:
                continue
            value = _value_after_label_match(body, match)
            if value:
                found[key] = value
                break
    return found


def extract_custom_fields_from_text(
    text: str | None,
    custom_keys: Sequence[str],
) -> dict[str, str]:
    """Best-effort label: value extraction for user-defined field keys."""
    return extract_label_value_fields_from_text(text, custom_keys)
