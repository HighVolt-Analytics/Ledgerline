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


def extract_label_value_fields_from_text(
    text: str | None,
    keys: Sequence[str],
) -> dict[str, str]:
    """Best-effort label: value extraction for configured field keys."""
    if not text or not str(text).strip() or not keys:
        return {}
    body = str(text)
    found: dict[str, str] = {}
    for raw_key in keys:
        key = str(raw_key or "").strip().lower()
        if not key or key in found:
            continue
        for label in _label_variants(key):
            pattern = re.compile(rf"(?i){re.escape(label)}\s*[:\-]\s*(.+)", re.M)
            match = pattern.search(body)
            if not match:
                continue
            value = match.group(1).strip().splitlines()[0].strip()[:_MAX_VALUE_LEN]
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
