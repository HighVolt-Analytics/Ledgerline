"""Deterministic fallbacks when structured line-item extraction returns nothing."""

from __future__ import annotations

from dataclasses import replace

from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem

FALLBACK_STRUCTURED = "fallback_structured"
FALLBACK_GRN_QTY = "fallback_grn_qty"
FALLBACK_HEADER = "fallback_header"


def _usable_rows(
    rows: list[ParsedLineItem],
    *,
    parsed: InvoiceData,
    allow_qty_only: bool,
) -> list[ParsedLineItem]:
    if not rows:
        return []
    return sanitize_line_items(
        rows,
        extracted_fields=parsed.extracted_fields,
        vendor=parsed.vendor,
        invoice_no=parsed.invoice_no,
        po_reference=parsed.po_reference,
        so_reference=(parsed.extracted_fields or {}).get("so_reference"),
        cost_centre=parsed.cost_centre,
        allow_qty_only=allow_qty_only,
    )


def _retry_structured_extraction(
    parsed: InvoiceData,
    text: str,
    payload: dict[str, object],
) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_parser import (
        document_has_charge_lines,
        document_has_line_item_table,
        document_has_qty_only_table,
        enrich_parsed_line_items,
        parse_charge_lines_from_text,
        parse_line_items_from_text,
        parse_qty_only_line_items_from_text,
        resolve_usable_line_items_from_payload,
    )

    qty_only = document_has_qty_only_table(text, payload)
    if not (
        document_has_line_item_table(text, payload)
        or qty_only
        or document_has_charge_lines(text)
    ):
        return []

    structured = resolve_usable_line_items_from_payload(payload, allow_qty_only=qty_only)
    money_structured = [
        row
        for row in structured
        if row.amount is not None or row.unit_price is not None
    ]
    # Prefer DI/layout money rows alone — do not union OCR text qty bleed when
    # authoritative product amounts already exist (e.g. SaaS invoices).
    if money_structured:
        tagged = [
            replace(row, source=row.source or FALLBACK_STRUCTURED) for row in money_structured
        ]
        return _usable_rows(tagged, parsed=parsed, allow_qty_only=False)

    candidates: list[ParsedLineItem] = list(structured)
    if document_has_charge_lines(text):
        candidates.extend(parse_charge_lines_from_text(text))
    candidates.extend(enrich_parsed_line_items(parse_line_items_from_text(text, payload)))
    if qty_only:
        candidates.extend(parse_qty_only_line_items_from_text(text))

    deduped: list[ParsedLineItem] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for row in candidates:
        key = (
            (row.description or "").strip().lower(),
            str(row.qty) if row.qty is not None else None,
            str(row.amount) if row.amount is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        tagged = replace(row, source=row.source or FALLBACK_STRUCTURED)
        deduped.append(tagged)
    return _usable_rows(deduped, parsed=parsed, allow_qty_only=qty_only)


def _grn_qty_fallback(parsed: InvoiceData, text: str) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_parser import (
        enrich_parsed_line_items,
        parse_line_items_from_text,
        parse_qty_only_line_items_from_text,
    )

    rows: list[ParsedLineItem] = []
    rows.extend(parse_qty_only_line_items_from_text(text))
    rows.extend(enrich_parsed_line_items(parse_line_items_from_text(text)))
    tagged = [replace(row, source=row.source or FALLBACK_GRN_QTY) for row in rows]
    return _usable_rows(tagged, parsed=parsed, allow_qty_only=True)


def _header_lump_sum_fallback(parsed: InvoiceData) -> list[ParsedLineItem]:
    """Disabled under grounded-only policy.

    Synthesizing qty=1 and unit_price=amount from header totals invents line
    fields that were not printed as line items. Leave line_items empty instead.
    """
    _ = parsed
    return []


def _bundle_role(dt_definition: object | None) -> str:
    if dt_definition is None:
        return ""
    return str(getattr(dt_definition, "purchase_bundle_role", "") or "").strip().lower()


def apply_line_items_fallback(
    parsed: InvoiceData,
    *,
    ocr_text: str | None = None,
    ocr_payload: dict[str, object] | None = None,
    dt_definition: object | None = None,
) -> tuple[InvoiceData, str | None]:
    """Fill line_items when primary extraction left the list empty."""
    if parsed.line_items:
        return parsed, None

    text = (ocr_text or parsed.document_text or "").strip()
    payload = dict(ocr_payload or {})
    bundle_role = _bundle_role(dt_definition)

    tiers: list[tuple[str, list[ParsedLineItem]]] = []
    if text:
        structured = _retry_structured_extraction(parsed, text, payload)
        if structured:
            tiers.append((FALLBACK_STRUCTURED, structured))
        if bundle_role == "grn":
            grn_rows = _grn_qty_fallback(parsed, text)
            if grn_rows:
                tiers.append((FALLBACK_GRN_QTY, grn_rows))

    header_rows = _header_lump_sum_fallback(parsed)
    if header_rows:
        tiers.append((FALLBACK_HEADER, header_rows))

    if not tiers:
        return parsed, None

    tier_name, rows = tiers[0]
    raw_fields = dict(parsed.raw_fields or {})
    raw_fields["_line_items_fallback"] = tier_name
    return replace(parsed, line_items=rows, raw_fields=raw_fields), tier_name
