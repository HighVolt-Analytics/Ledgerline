"""Deterministic field extraction from document layout structure."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.schemas.document_layout import DocumentLayoutResult, LayoutParagraph
from app.services.shared.amount_sanity import plausible_money, plausible_qty, sanitize_parsed_line_item
from app.services.extraction.document_heading_utils import extract_document_heading_signals, is_doc_title_line
from app.services.extraction.finance_field_labels import money_kv_label_patterns
from app.services.extraction.line_item_header_vocab import (
    DESC_HEADER_PREFERENCE_RE as _DESC_HEADER_PREFERENCE_RE,
    DESC_HEADER_RE as _DESC_HEADER_RE,
    META_HEADER_RE as _META_HEADER_RE,
    SERIAL_HEADER_RE as _SERIAL_HEADER_RE,
    UNIT_PRICE_HEADER_RE as _UNIT_PRICE_HEADER_RE,
    UOM_HEADER_RE as _UOM_HEADER_RE,
    is_amount_column_header,
    is_tax_column_header,
    is_unit_price_column_header,
    prefers_amount_header,
    qty_header_rank,
    select_best_qty_column,
)
from app.services.extraction.locale_vocab import optional_currency_code_group
from app.services.invoice.invoice_data import ParsedLineItem

DocFamilyHint = str

_KV_LABELS: list[tuple[str, re.Pattern[str]]] = [
    ("invoice_no", re.compile(r"(?i)^(?:invoice\s*(?:no|number|#)|inv\s*no|tax\s*invoice\s*no)\.?$")),
    ("po_reference", re.compile(r"(?i)^(?:po\s*(?:no|number|#)|purchase\s*order\s*(?:no|number|#)?)\.?$")),
    ("abn", re.compile(r"(?i)^(?:abn|australian\s+business\s+number)\.?$")),
    ("vendor", re.compile(r"(?i)^(?:vendor(?:\s*name)?|supplier(?:\s*name)?|from|bill\s*from|exporter)\.?$")),
    ("billing_address", re.compile(r"(?i)^(?:bill\s*to|ship\s*to|sold\s*to|billing\s*address|applicant|consignee)\.?$")),
    ("buyer_name", re.compile(r"(?i)^(?:customer(?:\s*name)?|client|buyer(?:\s*name)?|consignee|applicant(?:'?s?\s+name)?)\.?$")),
    ("seller_name", re.compile(r"(?i)^(?:seller(?:\s*name)?|supplier(?:\s*name)?|from|exporter|vendor(?:\s*name)?)\.?$")),
    ("so_reference", re.compile(r"(?i)^(?:so|sales\s*order)\s*(?:no|number|#)?\.?$")),
    ("account_code", re.compile(r"(?i)^(?:account\s*code|gl\s*code|a/?c\s*code)\.?$")),
    ("invoice_date", re.compile(r"(?i)^(?:invoice\s*date|date\s*of\s*issue|issue\s*date|document\s*date|date)\.?$")),
    ("due_date", re.compile(r"(?i)^(?:due\s*date|date\s*due|payment\s*due(?:\s*date)?)\.?$")),
    ("currency", re.compile(r"(?i)^(?:currency|ccy|curr)\.?$")),
    ("cost_centre", re.compile(r"(?i)^(?:cost\s*cent(?:re|er)|project\s*code|cost\s*code|\bcc\b)\.?$")),
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


def normalize_layout_kv_dict(raw: dict[str, str] | None) -> dict[str, str]:
    """Map raw Azure/layout labels (e.g. 'Invoice No') to canonical keys (invoice_no)."""
    if not raw:
        return {}
    found: dict[str, str] = {}
    for label, value in raw.items():
        token = str(value or "").strip()
        if not token:
            continue
        key = str(label or "").strip()
        # Already canonical
        if key in {
            "invoice_no",
            "po_reference",
            "abn",
            "vendor",
            "billing_address",
            "buyer_name",
            "seller_name",
            "so_reference",
            "account_code",
            "invoice_date",
            "due_date",
            "subtotal",
            "gst",
            "gst_rate",
            "total",
            "currency",
            "cost_centre",
            "grn_reference",
        }:
            found.setdefault(key, token)
            continue
        canonical = _normalize_field_key(key)
        if canonical:
            found.setdefault(canonical, token)
    return found


def _kv_label_pattern_for_text(pattern: re.Pattern[str]) -> str:
    """Drop end-anchor so 'Invoice No: INV-1' on one line can match."""
    source = pattern.pattern
    # Patterns are compiled as (?i)^...$ — strip trailing $ only
    if source.endswith("$"):
        source = source[:-1]
    return source


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
            label_re = _kv_label_pattern_for_text(pattern)
            if field_key == "invoice_no":
                match = re.search(
                    label_re + r"\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_]{2,})",
                    text,
                    re.I | re.M,
                )
                if match:
                    value = sanitize_invoice_no(match.group(1))
                    if value:
                        found[field_key] = value
                continue
            match = re.search(
                label_re + r"\s*[:\-]?\s*(.*)",
                text,
                re.I | re.M,
            )
            if match:
                value = match.group(1).strip().splitlines()[0].strip()
                if not value:
                    # Newline KV: Label\nvalue
                    tail = text[match.end() :]
                    for line in tail.splitlines():
                        token = line.strip()
                        if token and not _normalize_field_key(token):
                            value = token
                            break
                if value and not _normalize_field_key(value):
                    # Money keys must carry a printable amount — reject "TAX INVOICE" bleed.
                    if field_key in {"subtotal", "gst", "total"} and _money_value(value) is None:
                        continue
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


def _detect_headerless_line_item_columns(
    grid: dict[tuple[int, int], str],
    row_count: int,
    column_count: int,
) -> tuple[int, int, int, int, int] | None:
    """Infer desc/qty/price/amount columns from data rows when headers are missing.

    Returns (desc_col, qty_col, unit_price_col, tax_col, amount_col).
    tax_col stays -1 without a GST/tax header (no inferred tax).
    """
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
    tax_col = -1
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
    return (0, qty_col, unit_price_col, tax_col, amount_col)


def _is_totals_summary_table(
    grid: dict[tuple[int, int], str],
    row_count: int,
    column_count: int,
) -> bool:
    """True for 2-col Sub Total / CGST / Grand Total blocks (not product lines)."""
    if column_count != 2 or row_count < 2:
        return False
    from app.services.extraction.line_item_skip_patterns import is_summary_line_description

    summary_hits = 0
    sampled = 0
    for row in range(row_count):
        label = grid.get((row, 0), "").strip()
        if not label:
            continue
        sampled += 1
        if is_summary_line_description(label) or re.match(
            r"^(?:(?:grand\s+)?(?:sub\s*)?totals?|[csi]?gst|igst|utgst|vat|cess|"
            r"round\s*off|taxable\s*(?:amount|value)|(?:freight|discount)\s*totals?)\b",
            label,
            re.I,
        ):
            summary_hits += 1
    if sampled < 2:
        return False
    return summary_hits >= max(2, (sampled + 1) // 2)


def _is_kv_metadata_table(
    grid: dict[tuple[int, int], str],
    row_count: int,
    column_count: int,
) -> bool:
    """True when the table is a 2-col label→value block, not a product line table."""
    if column_count != 2 or row_count < 2:
        return False
    if _is_totals_summary_table(grid, row_count, column_count):
        return True
    from app.services.extraction.line_item_skip_patterns import (
        is_metadata_line_description,
        is_summary_line_description,
    )

    # Product tables advertise qty/price/amount headers — keep those.
    header0 = grid.get((0, 0), "").strip()
    header1 = grid.get((0, 1), "").strip()
    header_join = f"{header0} {header1}".lower()
    if re.search(
        r"\b(?:qty|quantity|unit\s*price|amount|rate|description|item|product)\b",
        header_join,
        re.I,
    ):
        return False

    label_hits = 0
    sampled = 0
    for row in range(row_count):
        label = grid.get((row, 0), "").strip()
        if not label:
            continue
        sampled += 1
        if (
            is_metadata_line_description(label)
            or _normalize_field_key(label)
            or is_summary_line_description(label)
        ):
            label_hits += 1
    if sampled < 2:
        return False
    return label_hits >= max(2, (sampled + 1) // 2)


def _parse_line_items_from_materialized_grid(
    grid: dict[tuple[int, int], str],
    row_count: int,
    column_count: int,
    *,
    trace: object | None = None,
) -> list[ParsedLineItem]:
    if row_count < 2 or column_count < 2:
        return []
    if _is_kv_metadata_table(grid, row_count, column_count):
        return []

    items: list[ParsedLineItem] = []
    desc_col = -1
    desc_cols: list[int] = []
    qty_col = -1
    unit_price_col = -1
    tax_col = -1
    amount_col = -1
    meta_cols: dict[int, str] = {}
    qty_headers: dict[int, str] = {}
    headers_detected = False
    for col in range(column_count):
        header = grid.get((0, col), "").lower().strip()
        if _SERIAL_HEADER_RE.match(header):
            headers_detected = True
            continue
        if _UOM_HEADER_RE.match(header) and not _UNIT_PRICE_HEADER_RE.search(header):
            meta_cols[col] = header
            headers_detected = True
            continue
        if _DESC_HEADER_RE.search(header) or re.search(r"\bmodel\b", header):
            desc_cols.append(col)
            # Prefer Name/Description over earlier weaker matches.
            if desc_col < 0 or _DESC_HEADER_PREFERENCE_RE.search(header):
                desc_col = col
            headers_detected = True
        # Collect qty candidates; bind by rank after the header scan.
        if qty_header_rank(header) is not None:
            qty_headers[col] = header
            headers_detected = True
        # Tax before amount/price so "GST Amount" / "Tax" never bind as line amount.
        if is_tax_column_header(header):
            tax_col = col
            headers_detected = True
            continue
        if is_unit_price_column_header(header):
            unit_price_col = col
            headers_detected = True
        elif is_amount_column_header(header):
            # Prefer dedicated amount headers over bare "total" when both exist.
            if amount_col < 0 or prefers_amount_header(header):
                amount_col = col
            headers_detected = True
        elif _META_HEADER_RE.search(header):
            meta_cols[col] = header
            headers_detected = True
    if qty_headers:
        qty_col = select_best_qty_column(qty_headers)
    if desc_col < 0:
        desc_col = 0
    if not headers_detected:
        inferred = _detect_headerless_line_item_columns(grid, row_count, column_count)
        if inferred is None:
            return []
        desc_col, qty_col, unit_price_col, tax_col, amount_col = inferred
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
            r"^(?:total|sub\s*total|subtotal|gst|tax|[csi]?gst|igst)\b|"
            r"\b(?:total\s+no\.?\s+of\s+pallet|no\.?\s+of\s+pallet)\b",
            desc,
            re.I,
        ):
            continue

        from app.services.extraction.line_item_skip_patterns import should_skip_line_row
        from app.services.extraction.line_item_noise_patterns import is_noise_line_item_row
        from app.services.extraction.line_item_trace import row_key_for_item

        skip_key = row_key_for_item(ParsedLineItem(description=desc))
        if should_skip_line_row(desc, trace=trace, row_key=skip_key):
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
        tax_amount = None
        if qty_col >= 0:
            qty_raw = grid.get((row, qty_col), "").strip()
            if qty_raw:
                try:
                    qty = plausible_qty(Decimal(re.sub(r"[^\d.]", "", qty_raw)))
                except InvalidOperation:
                    qty = None
        if unit_price_col >= 0:
            unit_price = _money_value(grid.get((row, unit_price_col), ""))
        if tax_col >= 0:
            tax_amount = _money_value(grid.get((row, tax_col), ""))
        if amount_col >= 0:
            amount = _money_value(grid.get((row, amount_col), ""))
        # Serial-only descriptions (S/N bleed) → recover product name from other cells.
        if re.fullmatch(r"\d{1,4}", desc or ""):
            for col in range(column_count):
                if col in {qty_col, unit_price_col, tax_col, amount_col} or col in meta_cols:
                    continue
                candidate = grid.get((row, col), "").strip()
                if candidate and not re.fullmatch(r"[\d.,$€£¥-]+", candidate.replace(" ", "")):
                    desc = candidate
                    break
        if qty is not None and prior_qtys and qty == sum(prior_qtys) and _is_layout_totals_row(desc, row_cells):
            continue
        if qty_only_table and qty is None:
            continue
        if not qty_only_table and amount is None and unit_price is None and qty is None:
            continue
        # Grounded-only: leave amount null when the amount cell is empty.

        if is_noise_line_item_row(desc, qty, trace=trace, row_key=skip_key):
            continue

        description = _append_meta_suffix(desc, meta_parts)
        if should_skip_line_row(description, trace=trace, row_key=skip_key):
            continue
        if is_noise_line_item_row(description, qty, trace=trace, row_key=skip_key):
            continue

        items.append(
            sanitize_parsed_line_item(
                ParsedLineItem(
                    description=description,
                    qty=qty,
                    unit_price=unit_price,
                    amount=amount,
                    tax_amount=tax_amount,
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


def parse_line_items_from_pdf_path(
    file_path: str | object,
    *,
    max_pages: int = 8,
    trace: object | None = None,
) -> list[ParsedLineItem]:
    """Parse product line rows from native PDF tables (PyMuPDF find_tables).

    Used when OCR/LLM left line_items empty but the PDF still has an embedded
    quantity/price grid (common on the vision understood path with sparse OCR).
    """
    try:
        import fitz
    except ImportError:
        return []

    path = str(file_path or "").strip()
    if not path:
        return []

    items: list[ParsedLineItem] = []
    try:
        doc = fitz.open(path)
    except Exception:
        return []
    try:
        page_limit = max(1, int(max_pages or 8))
        for page_index, page in enumerate(doc):
            if page_index >= page_limit:
                break
            try:
                finder = page.find_tables()
            except Exception:
                continue
            tables = getattr(finder, "tables", None) or []
            for table in tables:
                try:
                    raw = table.extract()
                except Exception:
                    continue
                if not raw or len(raw) < 2:
                    continue
                rows = [[str(cell or "").strip() for cell in row] for row in raw]
                items.extend(parse_line_items_from_table_grid(rows, trace=trace))
    finally:
        doc.close()
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
