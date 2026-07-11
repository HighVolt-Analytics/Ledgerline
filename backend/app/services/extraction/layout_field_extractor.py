"""Deterministic field extraction from document layout structure."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.schemas.document_layout import DocumentLayoutResult, LayoutParagraph
from app.services.shared.amount_sanity import plausible_money, plausible_qty, sanitize_parsed_line_item
from app.services.extraction.document_heading_utils import extract_document_heading_signals, is_doc_title_line
from app.services.extraction.finance_field_labels import money_kv_label_patterns
from app.services.extraction.locale_vocab import optional_currency_code_group
from app.services.invoice.invoice_data import ParsedLineItem

DocFamilyHint = str

_KV_LABELS: list[tuple[str, re.Pattern[str]]] = [
    ("invoice_no", re.compile(r"(?i)^(?:invoice\s*(?:no|number|#)|inv\s*no|tax\s*invoice\s*no)\.?$")),
    ("po_reference", re.compile(r"(?i)^(?:po\s*(?:no|number|#)|purchase\s*order\s*(?:no|number|#)?)\.?$")),
    ("abn", re.compile(r"(?i)^(?:abn|australian\s+business\s+number)\.?$")),
    ("vendor", re.compile(r"(?i)^(?:vendor|supplier|from|bill\s*from|exporter)\.?$")),
    ("billing_address", re.compile(r"(?i)^(?:bill\s*to|ship\s*to|sold\s*to|billing\s*address|applicant|consignee)\.?$")),
    ("buyer_name", re.compile(r"(?i)^(?:customer|client|buyer|consignee|applicant(?:'?s?\s+name)?)\.?$")),
    ("seller_name", re.compile(r"(?i)^(?:seller|supplier|from|exporter|vendor)\.?$")),
    ("so_reference", re.compile(r"(?i)^(?:so|sales\s*order)\s*(?:no|number|#)?\.?$")),
    ("account_code", re.compile(r"(?i)^(?:account\s*code|gl\s*code|a/?c\s*code)\.?$")),
    ("invoice_date", re.compile(r"(?i)^(?:invoice\s*date|date\s*of\s*issue|issue\s*date|document\s*date|date)\.?$")),
    ("due_date", re.compile(r"(?i)^(?:due\s*date|date\s*due|payment\s*due(?:\s*date)?)\.?$")),
    *money_kv_label_patterns(),
    ("grn_reference", re.compile(r"(?i)^(?:grn|goods\s*receipt|delivery\s*note)\s*(?:no|number|#)?\.?$")),
]

_FAMILY_PATTERNS: list[tuple[DocFamilyHint, re.Pattern[str]]] = [
    ("invoice", re.compile(r"(?i)\b(?:tax\s+invoice|commercial\s+invoice|invoice)\b")),
    ("po", re.compile(r"(?i)\bpurchase\s+order\b")),
    ("grn", re.compile(r"(?i)\b(?:goods\s+receipt|delivery\s+(?:note|docket)|\bgrn\b)\b")),
    ("contract", re.compile(r"(?i)\b(?:contract|agreement|master\s+service)\b")),
    ("quote", re.compile(r"(?i)\b(?:quotation|quote|estimate|proposal)\b")),
    ("credit_note", re.compile(r"(?i)\bcredit\s+note\b")),
    ("claim", re.compile(r"(?i)\b(?:expense\s+claim|reimbursement)\b")),
]


def _paragraph_top(polygon: tuple[float, ...]) -> float:
    if len(polygon) >= 2:
        ys = [polygon[i] for i in range(1, len(polygon), 2)]
        return min(ys) if ys else 9999.0
    return 9999.0


def extract_document_heading_from_layout(layout: DocumentLayoutResult | None) -> str | None:
    if layout is None:
        return None
    candidates: list[tuple[float, str]] = []
    for para in layout.top_paragraphs(limit=12):
        line = para.text.strip()
        if not line or len(line) > 120:
            continue
        if is_doc_title_line(line) or extract_document_heading_signals(line).primary_label:
            candidates.append((_paragraph_top(para.polygon), line))
    if not candidates:
        for para in layout.top_paragraphs(limit=6):
            line = para.text.strip()
            if line and len(line) <= 80:
                candidates.append((_paragraph_top(para.polygon), line))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0])
    return candidates[0][1]


def _normalize_field_key(label: str) -> str | None:
    cleaned = label.strip().rstrip(":")
    for field_key, pattern in _KV_LABELS:
        if pattern.search(cleaned):
            return field_key
    return None


def _money_value(raw: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return plausible_money(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def extract_key_value_fields(
    layout: DocumentLayoutResult | None,
    text: str,
) -> dict[str, str]:
    """Extract labeled fields from layout KV pairs and adjacent paragraph lines."""
    found: dict[str, str] = {}

    if layout is not None:
        for kv in layout.key_value_pairs:
            key = _normalize_field_key(kv.key) or _normalize_field_key(kv.key.rstrip(":"))
            if key and kv.value.strip():
                found.setdefault(key, kv.value.strip())

        paras = list(layout.paragraphs)
        for index, para in enumerate(paras):
            key = _normalize_field_key(para.text)
            if not key:
                continue
            for nxt in paras[index + 1 : index + 3]:
                if nxt.page_index != para.page_index:
                    break
                value = nxt.text.strip()
                if value and not _normalize_field_key(value):
                    found.setdefault(key, value)
                    break

    if text:
        from app.services.extraction.invoice_no_sanitizer import sanitize_invoice_no

        for field_key, pattern in _KV_LABELS:
            if field_key in found:
                continue
            if field_key == "invoice_no":
                match = re.search(
                    pattern.pattern + r"\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_]{2,})",
                    text,
                    re.I | re.M,
                )
                if match:
                    value = sanitize_invoice_no(match.group(1))
                    if value:
                        found[field_key] = value
                continue
            match = re.search(
                pattern.pattern + r"\s*[:\-]?\s*(.+)",
                text,
                re.I | re.M,
            )
            if match:
                value = match.group(1).strip().splitlines()[0].strip()
                if value:
                    found[field_key] = value
        if "total" not in found:
            freight = re.search(
                rf"FREIGHT\s*[:\-]?\s*{optional_currency_code_group()}\s*([\d,]+\.?\d*)",
                text,
                re.I,
            )
            if freight:
                found["total"] = freight.group(1).strip()

    return found


def _materialize_table_grid(table) -> dict[tuple[int, int], str]:
    """Expand row_span/column_span so merged cells populate every spanned slot."""
    grid: dict[tuple[int, int], str] = {}
    for cell in table.cells:
        text = cell.text.strip()
        row_span = max(1, int(cell.row_span or 1))
        col_span = max(1, int(cell.column_span or 1))
        for row_offset in range(row_span):
            for col_offset in range(col_span):
                grid[(cell.row_index + row_offset, cell.column_index + col_offset)] = text
    return grid


def _is_layout_totals_row(desc: str, row_cells: list[str]) -> bool:
    from app.services.extraction.line_item_skip_patterns import is_summary_line_description

    if is_summary_line_description(desc):
        return True
    if re.search(
        r"^\s*(?:TOTALS?|GRAND\s+TOTAL|SUB\s*TOTAL)\b",
        desc,
        re.I,
    ):
        return True
    for cell in row_cells:
        token = cell.strip()
        if not token:
            continue
        if re.search(r"^\s*(?:TOTALS?|GRAND\s+TOTAL|SUB\s*TOTAL)\b", token, re.I):
            return True
        if re.search(
            r"\b(?:total\s+net\s+weight|total\s+gross\s+weight|total\s+no\.?\s+of\s+pallet)\b",
            token,
            re.I,
        ):
            return True
    return False


def _append_meta_suffix(description: str, meta_parts: list[str]) -> str:
    suffix = " | ".join(part for part in meta_parts if part)
    if not suffix:
        return description
    if suffix.lower() in description.lower():
        return description
    return f"{description} | {suffix}"


_DESC_HEADER_RE = re.compile(
    r"desc|item|product|service|part|component|cpu|material|goods|line|details|sku|uom|part\s*no",
    re.I,
)


def _detect_headerless_line_item_columns(
    grid: dict[tuple[int, int], str],
    row_count: int,
    column_count: int,
) -> tuple[int, int, int, int] | None:
    """Infer desc/qty/price/amount columns from data rows when headers are missing."""
    if row_count < 2 or column_count < 2:
        return None
    sample_rows = min(row_count - 1, 4)
    text_hits = 0
    for row in range(1, 1 + sample_rows):
        first = grid.get((row, 0), "").strip()
        if first and not re.match(r"^[\d.,$€£¥-]+$", first):
            text_hits += 1
    if text_hits < max(1, sample_rows // 2):
        return None

    numeric_cols: list[int] = []
    for col in range(1, column_count):
        numeric_hits = 0
        for row in range(1, min(row_count, 5)):
            val = grid.get((row, col), "").strip()
            if val and re.match(r"^[\d,.$€£¥-]+$", val.replace(" ", "")):
                numeric_hits += 1
        if numeric_hits >= 1:
            numeric_cols.append(col)
    if not numeric_cols:
        return None

    qty_col = -1
    unit_price_col = -1
    amount_col = -1
    if len(numeric_cols) == 1:
        amount_col = numeric_cols[0]
    elif len(numeric_cols) == 2:
        qty_col = numeric_cols[0]
        amount_col = numeric_cols[1]
    else:
        qty_col = numeric_cols[0]
        unit_price_col = numeric_cols[1]
        amount_col = numeric_cols[-1]
    return (0, qty_col, unit_price_col, amount_col)


def _parse_line_items_from_materialized_grid(
    grid: dict[tuple[int, int], str],
    row_count: int,
    column_count: int,
    *,
    trace: object | None = None,
) -> list[ParsedLineItem]:
    if row_count < 2 or column_count < 2:
        return []

    items: list[ParsedLineItem] = []
    desc_col = 0
    desc_cols: list[int] = []
    qty_col = -1
    unit_price_col = -1
    amount_col = -1
    meta_cols: dict[int, str] = {}
    headers_detected = False
    for col in range(column_count):
        header = grid.get((0, col), "").lower()
        if _DESC_HEADER_RE.search(header):
            desc_cols.append(col)
            desc_col = col
            headers_detected = True
        elif re.search(r"model", header):
            desc_cols.append(col)
            if desc_col == 0 and not grid.get((0, desc_col), "").strip():
                desc_col = col
            headers_detected = True
        if re.search(r"qty|quantity|q'?ty|pcs", header):
            qty_col = col
            headers_detected = True
        if re.search(r"unit\s*price|rate|price\s*ea|price\s*excl|unit\s*cost|(?:^|\s)each(?:\s|$)", header):
            unit_price_col = col
            headers_detected = True
        elif re.search(r"amount|line\s*total|extended|line\s*amount|value|ex\s*gst", header) and not re.search(
            r"subtotal|grand", header
        ):
            amount_col = col
            headers_detected = True
        elif re.search(r"^total$", header):
            amount_col = col
            headers_detected = True
        elif re.search(r"^price$|\bprice\b", header) and unit_price_col < 0 and amount_col < 0:
            unit_price_col = col
            headers_detected = True
        elif re.search(r"\bplt|pallet|dimension|coo|origin|weight|hs|harmonized", header):
            meta_cols[col] = header
            headers_detected = True
    if not headers_detected:
        inferred = _detect_headerless_line_item_columns(grid, row_count, column_count)
        if inferred is None:
            return []
        desc_col, qty_col, unit_price_col, amount_col = inferred
        desc_cols = [desc_col] if desc_col >= 0 else []

    data_start_row = 1 if headers_detected else 0
    qty_only_table = qty_col >= 0 and unit_price_col < 0 and amount_col < 0
    carry_meta: dict[int, str] = {}
    prior_qtys: list[Decimal] = []

    for row in range(data_start_row, row_count):
        row_cells = [grid.get((row, col), "").strip() for col in range(column_count)]
        desc = grid.get((row, desc_col), "").strip()
        if desc_cols:
            desc_parts = [
                grid.get((row, col), "").strip()
                for col in desc_cols
                if col != qty_col and grid.get((row, col), "").strip()
            ]
            if desc_parts:
                desc = " ".join(desc_parts)
        if not desc and qty_only_table:
            for col in range(column_count):
                if col == qty_col:
                    continue
                if re.search(
                    r"desc|item|product|part|component|model|cpu|material|goods",
                    grid.get((0, col), "").lower(),
                ):
                    candidate = grid.get((row, col), "").strip()
                    if candidate:
                        desc = candidate
                        desc_col = col
                        break
        if _is_layout_totals_row(desc, row_cells):
            if trace is not None:
                from app.services.extraction.line_item_trace import row_key_for_item

                trace.record(
                    row_key_for_item(ParsedLineItem(description=desc)),
                    "layout_totals",
                    "dropped",
                    "layout_totals_row",
                )
            continue
        if not desc or re.search(
            r"^(?:total|subtotal|gst|tax)\b|\b(?:total\s+no\.?\s+of\s+pallet|no\.?\s+of\s+pallet)\b",
            desc,
            re.I,
        ):
            continue

        meta_parts: list[str] = []
        for col, header in meta_cols.items():
            value = grid.get((row, col), "").strip()
            if value:
                carry_meta[col] = value
            elif col in carry_meta:
                value = carry_meta[col]
            if value:
                meta_parts.append(value)

        qty = None
        unit_price = None
        amount = None
        if qty_col >= 0:
            qty_raw = grid.get((row, qty_col), "").strip()
            if qty_raw:
                try:
                    qty = plausible_qty(Decimal(re.sub(r"[^\d.]", "", qty_raw)))
                except InvalidOperation:
                    qty = None
        if unit_price_col >= 0:
            unit_price = _money_value(grid.get((row, unit_price_col), ""))
        if amount_col >= 0:
            amount = _money_value(grid.get((row, amount_col), ""))
        if qty is not None and prior_qtys and qty == sum(prior_qtys) and _is_layout_totals_row(desc, row_cells):
            continue
        if qty_only_table and qty is None:
            continue
        if not qty_only_table and amount is None and unit_price is None and qty is None:
            continue
        if amount is None and qty is not None and unit_price is not None:
            amount = plausible_money(qty * unit_price)

        description = _append_meta_suffix(desc, meta_parts)
        items.append(
            sanitize_parsed_line_item(
                ParsedLineItem(
                    description=description,
                    qty=qty,
                    unit_price=unit_price,
                    amount=amount,
                    source="table",
                )
            )
        )
        if qty is not None:
            prior_qtys.append(qty)

    return items


def parse_line_items_from_table_grid(
    rows: list[list[str]],
    *,
    trace: object | None = None,
) -> list[ParsedLineItem]:
    """Parse line items from a serialized layout table grid (list of rows)."""
    if not rows or len(rows) < 2:
        return []
    row_count = len(rows)
    column_count = max(len(row) for row in rows)
    grid: dict[tuple[int, int], str] = {}
    for row_index, row in enumerate(rows):
        for col_index in range(column_count):
            grid[(row_index, col_index)] = row[col_index].strip() if col_index < len(row) else ""
    return _parse_line_items_from_materialized_grid(
        grid, row_count, column_count, trace=trace
    )


def extract_line_items_from_tables(
    layout: DocumentLayoutResult | None,
    *,
    trace: object | None = None,
) -> list[ParsedLineItem]:
    if layout is None or not layout.tables:
        return []

    items: list[ParsedLineItem] = []
    for table in layout.tables:
        if table.row_count < 2 or table.column_count < 2:
            continue
        grid = _materialize_table_grid(table)
        items.extend(
            _parse_line_items_from_materialized_grid(
                grid, table.row_count, table.column_count, trace=trace
            )
        )

    return items


def infer_doc_family_hint(
    layout: DocumentLayoutResult | None,
    heading: str | None,
    text: str,
) -> DocFamilyHint | None:
    corpus = " ".join(
        part
        for part in [
            heading or "",
            text[:2000] if text else "",
            *(p.text for p in (layout.top_paragraphs(limit=6) if layout else [])),
        ]
        if part
    )
    if not corpus.strip():
        return None
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(corpus):
            return family
    if layout and layout.has_tables and re.search(r"(?i)\bpo\b", corpus):
        return "po"
    return None


def layout_hint_suggests_invoice(hint: DocFamilyHint | None) -> bool:
    return hint in {None, "invoice", "credit_note"}
