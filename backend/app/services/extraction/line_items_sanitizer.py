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


def _passes_minimum_product_row(item: ParsedLineItem, *, allow_qty_only: bool = False) -> bool:
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
    if allow_qty_only and has_qty:
        return True
    return False


def _duplicates_header_value(desc: str, header_values: set[str]) -> bool:
    normalized = _normalize_text(desc)
    if not normalized or len(normalized) < 3:
        return False
    if normalized in header_values:
        return True
    for value in header_values:
        if len(value) < 8:
            continue
        # Exact containment either way — but ignore misparsed "vendor" blobs that
        # are really product lines (qty + money) swallowing the real description.
        if value in normalized or normalized in value:
            if normalized in value and len(value) > len(normalized) + 8:
                # Decimals may be OCR-normalized away ("50.00" → "50 00"); still
                # treat multi-numeric tails as product-line bleed, not vendor labels.
                looks_like_line_bleed = bool(
                    re.search(r"\d+\.\d{2}", value)
                    or re.search(r"\b\d+\b(?:\s+\d+){2,}", value)
                )
                if looks_like_line_bleed and re.search(r"\b\d+\b", value):
                    continue
            return True
    return False


def _has_money_bearing_rows(items: list[ParsedLineItem]) -> bool:
    """True when a real product row (not summary/noise) has amount or unit price."""
    from app.services.extraction.line_item_noise_patterns import is_noise_line_item_row

    for item in items:
        desc = item.description or ""
        if should_skip_line_row(desc):
            continue
        if is_noise_line_item_row(desc, item.qty):
            continue
        if item.amount is not None or item.unit_price is not None:
            return True
    return False


def sanitize_line_items(
    items: list[ParsedLineItem],
    *,
    extracted_fields: Mapping[str, str] | None = None,
    vendor: str | None = None,
    invoice_no: str | None = None,
    po_reference: str | None = None,
    so_reference: str | None = None,
    cost_centre: str | None = None,
    allow_qty_only: bool = False,
    trace: object | None = None,
) -> list[ParsedLineItem]:
    """Drop summary/metadata/header duplicate rows from merged line items."""
    from app.services.extraction.line_item_trace import row_key_for_item

    header_values = _header_scalar_values(
        vendor=vendor,
        invoice_no=invoice_no,
        po_reference=po_reference,
        so_reference=so_reference,
        cost_centre=cost_centre,
        extracted_fields=extracted_fields,
    )
    # When money-bearing product rows already exist, do not keep qty-only OCR bleed
    # (addresses, page footers, "USD due …") that survived allow_qty_only=True.
    effective_allow_qty_only = allow_qty_only and not _has_money_bearing_rows(items)

    cleaned: list[ParsedLineItem] = []
    for index, item in enumerate(items):
        desc = item.description or ""
        row_key = row_key_for_item(item, index)
        if should_skip_line_row(desc, trace=trace, row_key=row_key):
            continue
        if _is_label_only_row(item):
            if trace is not None:
                trace.record(row_key, "sanitize", "dropped", "label_only")
            continue
        if _duplicates_header_value(desc, header_values):
            if trace is not None:
                trace.record(row_key, "sanitize", "dropped", "header_duplicate")
            continue
        from app.services.extraction.line_item_noise_patterns import is_noise_line_item_row

        if is_noise_line_item_row(desc, item.qty, trace=trace, row_key=row_key):
            continue
        if not _passes_minimum_product_row(item, allow_qty_only=effective_allow_qty_only):
            if trace is not None:
                reason = (
                    "qty_only_with_money_rows"
                    if allow_qty_only and not effective_allow_qty_only
                    else "minimum_row"
                )
                trace.record(row_key, "sanitize", "dropped", reason)
            continue
        if trace is not None:
            trace.record(row_key, "sanitize", "kept", "product_row")
        cleaned.append(item)

    from app.services.extraction.line_items_parser import dedupe_near_duplicate_line_items

    return dedupe_near_duplicate_line_items(cleaned)