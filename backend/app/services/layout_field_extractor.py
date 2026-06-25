"""Deterministic field extraction from document layout structure."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.schemas.document_layout import DocumentLayoutResult, LayoutParagraph
from app.services.amount_sanity import plausible_money
from app.services.document_heading_utils import extract_document_heading_signals, is_doc_title_line
from app.services.invoice_data import ParsedLineItem

DocFamilyHint = str

_KV_LABELS: list[tuple[str, re.Pattern[str]]] = [
    ("invoice_no", re.compile(r"(?i)^(?:invoice\s*(?:no|number|#)|inv\s*no|tax\s*invoice\s*no)\.?$")),
    ("po_reference", re.compile(r"(?i)^(?:po\s*(?:no|number|#)|purchase\s*order\s*(?:no|number|#)?)\.?$")),
    ("abn", re.compile(r"(?i)^(?:abn|australian\s+business\s+number)\.?$")),
    ("vendor", re.compile(r"(?i)^(?:vendor|supplier|from|bill\s*from)\.?$")),
    ("invoice_date", re.compile(r"(?i)^(?:invoice\s*date|date|issue\s*date)\.?$")),
    ("due_date", re.compile(r"(?i)^(?:due\s*date|payment\s*due)\.?$")),
    ("total", re.compile(r"(?i)^(?:total|amount\s*due|grand\s*total)\.?$")),
    ("subtotal", re.compile(r"(?i)^(?:sub\s*total|subtotal)\.?$")),
    ("gst", re.compile(r"(?i)^(?:gst|tax|vat)\.?$")),
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
        for field_key, pattern in _KV_LABELS:
            if field_key in found:
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

    return found


def extract_line_items_from_tables(layout: DocumentLayoutResult | None) -> list[ParsedLineItem]:
    if layout is None or not layout.tables:
        return []

    items: list[ParsedLineItem] = []
    for table in layout.tables:
        if table.row_count < 2 or table.column_count < 2:
            continue
        grid: dict[tuple[int, int], str] = {
            (cell.row_index, cell.column_index): cell.text for cell in table.cells
        }
        header_row = grid.get((0, 0), "").lower()
        desc_col = 0
        qty_col = -1
        amount_col = -1
        for col in range(table.column_count):
            header = grid.get((0, col), "").lower()
            if re.search(r"desc|item|product|service", header):
                desc_col = col
            if re.search(r"qty|quantity", header):
                qty_col = col
            if re.search(r"amount|total|price", header):
                amount_col = col
        if not header_row and table.column_count >= 3:
            qty_col = 1
            amount_col = table.column_count - 1

        for row in range(1, table.row_count):
            desc = grid.get((row, desc_col), "").strip()
            if not desc or re.search(r"^(?:total|subtotal|gst|tax)\b", desc, re.I):
                continue
            qty = None
            amount = None
            if qty_col >= 0:
                qty_raw = grid.get((row, qty_col), "").strip()
                if qty_raw:
                    try:
                        qty = Decimal(re.sub(r"[^\d.]", "", qty_raw))
                    except InvalidOperation:
                        qty = None
            if amount_col >= 0:
                amount = _money_value(grid.get((row, amount_col), ""))
            items.append(ParsedLineItem(description=desc, qty=qty, amount=amount))

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
