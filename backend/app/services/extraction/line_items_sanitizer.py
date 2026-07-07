"""Post-merge line item sanitization — remove header/metadata rows from product tables."""

from __future__ import annotations

import re
from typing import Mapping

from app.services.extraction.line_item_skip_patterns import (
    HEADER_DEDUP_EXTRACTED_FIELD_KEYS,
    is_metadata_line_description,
    should_skip_line_row,
)
from app.services.invoice.invoice_data import ParsedLineItem


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _header_scalar_values(
    *,
    vendor: str | None = None,
    invoice_no: str | None = None,
    po_reference: str | None = None,
    so_reference: str | None = None,
    cost_centre: str | None = None,
    extracted_fields: Mapping[str, str] | None = None,
) -> set[str]:
    values: set[str] = set()
    for raw in (vendor, invoice_no, po_reference, so_reference, cost_centre):
        token = _normalize_text(raw)
        if token and len(token) >= 3:
            values.add(token)
    for key in HEADER_DEDUP_EXTRACTED_FIELD_KEYS:
        if extracted_fields and extracted_fields.get(key):
            token = _normalize_text(str(extracted_fields[key]))
            if token and len(token) >= 3:
                values.add(token)
    return values


def _is_label_only_row(item: ParsedLineItem) -> bool:
    desc = item.description or ""
    if not is_metadata_line_description(desc):
        return False
    has_money = item.amount is not None or item.unit_price is not None
    return not has_money


def _passes_minimum_product_row(item: ParsedLineItem) -> bool:
    desc = re.sub(r"\s+", " ", (item.description or "").strip())
    if not desc:
        return False
    if should_skip_line_row(desc):
        return False
    has_money = item.amount is not None or item.unit_price is not None
    has_qty = item.qty is not None
    if has_money:
        return True
    if has_qty and (item.amount is not None or item.unit_price is not None):
        return True
    return False


def _duplicates_header_value(desc: str, header_values: set[str]) -> bool:
    normalized = _normalize_text(desc)
    if not normalized or len(normalized) < 3:
        return False
    if normalized in header_values:
        return True
    for value in header_values:
        if len(value) >= 8 and (value in normalized or normalized in value):
            return True
    return False


def sanitize_line_items(
    items: list[ParsedLineItem],
    *,
    ocr_text: str | None = None,
    extracted_fields: Mapping[str, str] | None = None,
    vendor: str | None = None,
    invoice_no: str | None = None,
    po_reference: str | None = None,
    so_reference: str | None = None,
    cost_centre: str | None = None,
) -> list[ParsedLineItem]:
    """Drop summary/metadata/header duplicate rows from merged line items."""
    del ocr_text  # reserved for future OCR cross-checks
    header_values = _header_scalar_values(
        vendor=vendor,
        invoice_no=invoice_no,
        po_reference=po_reference,
        so_reference=so_reference,
        cost_centre=cost_centre,
        extracted_fields=extracted_fields,
    )

    cleaned: list[ParsedLineItem] = []
    for item in items:
        desc = item.description or ""
        if should_skip_line_row(desc):
            continue
        if _is_label_only_row(item):
            continue
        if _duplicates_header_value(desc, header_values):
            continue
        if not _passes_minimum_product_row(item):
            continue
        cleaned.append(item)
    return cleaned
