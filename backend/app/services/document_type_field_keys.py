"""Canonical and user-defined extraction field keys for document-type catalogue."""

from __future__ import annotations

import re

# Populated by ingest/OCR — never block playbook posting when starred by mistake.
INFRASTRUCTURE_EXTRACTION_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "attachment_name",
        "document_text",
    }
)

CANONICAL_EXTRACTION_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "vendor",
        "invoice_no",
        "po_reference",
        "so_reference",
        "total",
        "subtotal",
        "gst",
        "abn",
        "invoice_date",
        "due_date",
        "line_items",
        "bank_details",
        "attachment_name",
        "cost_centre",
        "billing_address",
        "email_subject",
        "account_code",
        "account_name",
        "document_text",
        "document_heading",
    }
)

_CUSTOM_FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def is_valid_extraction_field_key(key: str) -> bool:
    normalized = key.strip().lower()
    if not normalized:
        return False
    if normalized in CANONICAL_EXTRACTION_FIELD_KEYS:
        return True
    return bool(_CUSTOM_FIELD_KEY.match(normalized))


def playbook_blockable_field_keys(keys: list[str] | None) -> list[str]:
    """Compulsory keys that may block playbook — excludes ingest/OCR infrastructure."""
    return [
        key
        for key in normalize_extraction_field_keys(keys)
        if key not in INFRASTRUCTURE_EXTRACTION_FIELD_KEYS
    ]


def normalize_extraction_field_keys(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in values:
        key = raw.strip().lower()
        if not key or key in seen or not is_valid_extraction_field_key(key):
            continue
        seen.add(key)
        normalized.append(key)
    return normalized
