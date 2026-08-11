"""Deterministic fallbacks when structured line-item extraction returns nothing.

Source ranking is owned by ``line_item_extraction_policy`` so money invoices never
accept qty-only OCR bleed, and sparse vision OCR prefers native PDF tables.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.extraction.line_item_extraction_policy import (
    PRIORITY_GRN_QTY,
    PRIORITY_PAYLOAD,
    PRIORITY_PDF,
    PRIORITY_PDF_SPARSE,
    PRIORITY_TEXT_MONEY,
    PRIORITY_TEXT_QTY,
    LineDocumentShape,
    classify_line_document_shape,
    filter_rows_for_shape,
    is_sparse_ocr_payload,
    money_bearing_rows,
    pick_best_fallback_tier,
)
from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem

FALLBACK_STRUCTURED = "fallback_structured"
FALLBACK_PDF_TABLES = "fallback_pdf_tables"
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


def _tag(rows: list[ParsedLineItem], source: str) -> list[ParsedLineItem]:
    return [replace(row, source=row.source or source) for row in rows]


def _payload_structured_rows(
    parsed: InvoiceData,
    payload: dict[str, object],
    shape: LineDocumentShape,
) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_parser import resolve_usable_line_items_from_payload

    allow_qty = shape == LineDocumentShape.QTY_ONLY
    structured = resolve_usable_line_items_from_payload(payload, allow_qty_only=allow_qty)
    if shape == LineDocumentShape.MONEY:
        money = money_bearing_rows(structured)
        if money:
            return _usable_rows(
                _tag(money, FALLBACK_STRUCTURED),
                parsed=parsed,
                allow_qty_only=False,
            )
        return []
    filtered = filter_rows_for_shape(structured, shape)
    return _usable_rows(
        _tag(filtered, FALLBACK_STRUCTURED),
        parsed=parsed,
        allow_qty_only=allow_qty,
    )


def _text_structured_rows(
    parsed: InvoiceData,
    text: str,
    payload: dict[str, object],
    shape: LineDocumentShape,
) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_parser import (
        document_has_charge_lines,
        document_has_line_item_table,
        enrich_parsed_line_items,
        parse_charge_lines_from_text,
        parse_line_items_from_text,
        parse_qty_only_line_items_from_text,
        text_has_money_product_signals,
    )

    if not text.strip():
        return []

    money_invoice = shape == LineDocumentShape.MONEY or text_has_money_product_signals(text)
    qty_only = shape == LineDocumentShape.QTY_ONLY
    if not (
        document_has_line_item_table(text, payload)
        or qty_only
        or document_has_charge_lines(text)
        or money_invoice
        or shape == LineDocumentShape.UNKNOWN
    ):
        return []

    candidates: list[ParsedLineItem] = []
    if document_has_charge_lines(text) or shape == LineDocumentShape.CHARGE:
        candidates.extend(parse_charge_lines_from_text(text))

    # Money / unknown: parse product tables (vertical + horizontal). Never qty-only bleed.
    if shape in {LineDocumentShape.MONEY, LineDocumentShape.UNKNOWN, LineDocumentShape.CHARGE}:
        candidates.extend(enrich_parsed_line_items(parse_line_items_from_text(text, payload)))
    elif qty_only:
        candidates.extend(parse_qty_only_line_items_from_text(text))
        candidates.extend(enrich_parsed_line_items(parse_line_items_from_text(text, payload)))

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
        deduped.append(row)

    allow_qty = shape == LineDocumentShape.QTY_ONLY
    usable = _usable_rows(
        _tag(deduped, FALLBACK_STRUCTURED),
        parsed=parsed,
        allow_qty_only=allow_qty,
    )
    return filter_rows_for_shape(usable, shape if shape != LineDocumentShape.UNKNOWN else (
        LineDocumentShape.MONEY if money_bearing_rows(usable) else LineDocumentShape.QTY_ONLY
    ))


def _grn_qty_fallback(parsed: InvoiceData, text: str) -> list[ParsedLineItem]:
    from app.services.extraction.line_items_parser import (
        enrich_parsed_line_items,
        parse_line_items_from_text,
        parse_qty_only_line_items_from_text,
    )

    rows: list[ParsedLineItem] = []
    rows.extend(parse_qty_only_line_items_from_text(text))
    rows.extend(enrich_parsed_line_items(parse_line_items_from_text(text)))
    tagged = _tag(rows, FALLBACK_GRN_QTY)
    return _usable_rows(tagged, parsed=parsed, allow_qty_only=True)


def _header_lump_sum_fallback(
    parsed: InvoiceData,
    *,
    sparse_ocr: bool,
    requires_lines: bool,
) -> list[ParsedLineItem]:
    """Last resort when no other tier produced rows but a printed total exists.

    Copies the grounded header ``total`` into one amount-only line. Does **not**
    invent qty or unit_price. Used when the DT requires line items — including
    vision extracts whose OCR provider looks "rich" but yields no usable rows.
    """
    _ = sparse_ocr
    if not requires_lines:
        return []
    if parsed.total is None:
        return []
    from app.services.shared.amount_sanity import plausible_money

    amount = plausible_money(parsed.total)
    if amount is None or amount <= 0:
        return []
    heading = (parsed.document_heading or "").strip()
    description = heading[:200] if heading else None
    return [
        ParsedLineItem(
            description=description,
            amount=amount,
            source=FALLBACK_HEADER,
        )
    ]


def _bundle_role(dt_definition: object | None) -> str:
    if dt_definition is None:
        return ""
    return str(getattr(dt_definition, "purchase_bundle_role", "") or "").strip().lower()


def _pdf_table_fallback(
    parsed: InvoiceData,
    pdf_path: str | None,
    shape: LineDocumentShape,
) -> list[ParsedLineItem]:
    path = str(pdf_path or "").strip()
    if not path:
        return []
    from app.services.extraction.layout_field_extractor import parse_line_items_from_pdf_path

    rows = parse_line_items_from_pdf_path(path)
    tagged = _tag(rows, FALLBACK_PDF_TABLES)
    allow_qty = shape == LineDocumentShape.QTY_ONLY
    usable = _usable_rows(tagged, parsed=parsed, allow_qty_only=allow_qty)
    return filter_rows_for_shape(usable, shape)


def apply_line_items_fallback(
    parsed: InvoiceData,
    *,
    ocr_text: str | None = None,
    ocr_payload: dict[str, object] | None = None,
    dt_definition: object | None = None,
    pdf_path: str | object | None = None,
    require_lines: bool | None = None,
) -> tuple[InvoiceData, str | None]:
    """Fill line_items when primary extraction left the list empty.

    Ranking (application policy):
    1. DI / layout payload money rows
    2. Native PDF tables (especially when OCR is sparse / vision stub)
    3. OCR/document_text money-bearing structured parse
    4. GRN qty-only when DT bundle role is grn
    5. Sparse vision + required lines: amount-only row from grounded header total
       (no invented qty/unit_price; never used when OCR text is rich enough)
    Never accept address/phone qty bleed on money docs.
    """
    if parsed.line_items:
        return parsed, None

    text = (ocr_text or parsed.document_text or "").strip()
    payload = dict(ocr_payload or {})
    shape = classify_line_document_shape(
        text,
        payload,
        dt_definition=dt_definition,
        parsed=parsed,
    )
    # Empty OCR text on vision stubs must count as sparse even if provider is odd.
    sparse = is_sparse_ocr_payload(payload) or not text
    bundle_role = _bundle_role(dt_definition)
    from app.services.extraction.line_item_extraction_policy import (
        document_requires_line_items,
        team_expense_hard_requires_line_items,
    )

    if require_lines is not None:
        requires_lines = bool(require_lines)
    else:
        try:
            requires_lines = bool(team_expense_hard_requires_line_items(dt_definition))
        except Exception:
            requires_lines = document_requires_line_items(dt_definition)

    candidates: list[tuple[str, list[ParsedLineItem], int]] = []

    payload_rows = _payload_structured_rows(parsed, payload, shape)
    if payload_rows:
        candidates.append((FALLBACK_STRUCTURED, payload_rows, PRIORITY_PAYLOAD))

    pdf_rows = _pdf_table_fallback(parsed, pdf_path, shape)
    if pdf_rows:
        pdf_priority = PRIORITY_PDF_SPARSE if sparse else PRIORITY_PDF
        # Prefer PDF over weak text when money shape and PDF has money rows.
        if shape == LineDocumentShape.MONEY and money_bearing_rows(pdf_rows) and sparse:
            pdf_priority = PRIORITY_PDF_SPARSE
        candidates.append((FALLBACK_PDF_TABLES, pdf_rows, pdf_priority))

    if text:
        text_rows = _text_structured_rows(parsed, text, payload, shape)
        if text_rows:
            priority = (
                PRIORITY_TEXT_QTY
                if shape == LineDocumentShape.QTY_ONLY
                else PRIORITY_TEXT_MONEY
            )
            candidates.append((FALLBACK_STRUCTURED, text_rows, priority))

        if bundle_role == "grn":
            grn_rows = _grn_qty_fallback(parsed, text)
            if grn_rows:
                candidates.append((FALLBACK_GRN_QTY, grn_rows, PRIORITY_GRN_QTY))

    header_rows = _header_lump_sum_fallback(
        parsed,
        sparse_ocr=sparse,
        requires_lines=requires_lines,
    )
    if header_rows:
        candidates.append((FALLBACK_HEADER, header_rows, 99))

    picked = pick_best_fallback_tier(candidates)
    if picked is None:
        return parsed, None

    tier_name, rows = picked
    raw_fields = dict(parsed.raw_fields or {})
    raw_fields["_line_items_fallback"] = tier_name
    raw_fields["_line_items_shape"] = shape.value
    return replace(parsed, line_items=rows, raw_fields=raw_fields), tier_name
