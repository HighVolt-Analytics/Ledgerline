"""Shared line-item table header vocabulary (DT-agnostic).

Used by layout grid parsing, vertical OCR, and skip patterns so column binding
does not drift per document sample.
"""

from __future__ import annotations

import re

# Prefer accepted/received over ordered/generic qty (column-order independent).
QTY_HEADER_RANK: tuple[tuple[int, re.Pattern[str]], ...] = (
    (0, re.compile(r"(?:^|\b)(?:accepted(?:\s*qty)?|qty\s*accepted)(?:\b|$)", re.I)),
    (1, re.compile(r"(?:^|\b)(?:rec(?:ei)?(?:ved|d)\s*qty|qty\s*rec(?:ei)?(?:ved|d)?)(?:\b|$)", re.I)),
    (2, re.compile(r"(?:^|\b)(?:po\s*qty|ordered(?:\s*qty)?|order\s*qty|qty\s*ordered)(?:\b|$)", re.I)),
    (3, re.compile(r"(?:^|\b)(?:qty|quantity|q'?ty)(?:\b|$)|^pcs$", re.I)),
)

DESC_HEADER_RE = re.compile(
    r"(?:^|\b)(?:desc(?:ription)?|item(?:\s*description)?|product(?:\s*name)?|"
    r"service|part(?:\s*no)?|component|cpu|material|goods|details|sku|name|"
    r"particulars?)(?:\b|$)",
    re.I,
)

SERIAL_HEADER_RE = re.compile(
    r"^(?:s/?n|s\.?\s*n\.?|sl\.?\s*no\.?|s\.?\s*no\.?|no\.?|#|item\s*no|line\s*no)$",
    re.I,
)

UOM_HEADER_RE = re.compile(
    r"^(?:unit|uom|pcs|nos?|ea|kg|box|pair|tray|type)(?:\s*\([^)]*\))?$",
    re.I,
)

TAX_HEADER_RE = re.compile(
    r"^(?:gst|tax|vat|[csi]?gst|igst|utgst|cess)\b|"
    r"(?:^|\s)(?:gst|tax|vat|[csi]?gst|igst)\s*(?:amount|amt)?$",
    re.I,
)

UNIT_PRICE_HEADER_RE = re.compile(
    r"unit\s*price|unit\s*rate|u/?price|rate|price\s*ea|price\s*excl|unit\s*cost|"
    r"(?:^|\s)each(?:\s|$)|^price$|(?<!line\s)\bprice\b(?!\s*(?:total|amount))",
    re.I,
)

AMOUNT_HEADER_RE = re.compile(
    r"amount|line\s*total|extended|line\s*amount|net\s*amount|value|ex\s*gst|"
    r"incl(?:uding)?\s*gst|^total$|(?<!unit\s)\btotal\b",
    re.I,
)

AMOUNT_FOOTER_HEADER_RE = re.compile(
    r"sub\s*total|subtotal|grand\s*total|\bgrand\b",
    re.I,
)

META_HEADER_RE = re.compile(
    r"\bplt|pallet|dimension|coo|origin|weight|hs|harmonized",
    re.I,
)

# Stronger description headers win when multiple match.
DESC_HEADER_PREFERENCE_RE = re.compile(r"name|desc|item|product|model", re.I)

VERTICAL_DESC_HEADER_RE = re.compile(
    r"^(?:description|item(?:\s*description)?|product(?:\s*name)?|name|particulars?)$",
    re.I,
)
VERTICAL_QTY_HEADER_RE = re.compile(
    r"^(?:qty|quantity|q'?ty|recd\s*qty|received\s*qty|accepted(?:\s*qty)?|"
    r"po\s*qty|ordered(?:\s*qty)?)$",
    re.I,
)
VERTICAL_UNIT_PRICE_HEADER_RE = re.compile(
    r"^(?:unit\s*price|unit\s*rate|u/?price|rate)(?:\s*\([^)]*\))?$",
    re.I,
)
VERTICAL_TAX_HEADER_RE = re.compile(
    r"^(?:gst|tax|vat|[csi]?gst|igst|utgst|cess)(?:\s*amount)?$",
    re.I,
)
VERTICAL_AMOUNT_HEADER_RE = re.compile(
    r"^(?:amount|line\s*total|extended|value)(?:\s*\([^)]*\))?$",
    re.I,
)
VERTICAL_SKIP_HEADER_RE = re.compile(
    r"^(?:s/?n|s\.?\s*n\.?|type|unit(?:\s*\([^)]*\))?|uom|pcs|tray|nos?)$",
    re.I,
)

# Bare table-header cells (including Name) that must not become product rows.
TABLE_HEADER_CELL_RE = re.compile(
    r"^(?:description|item(?:\s*description)?|product(?:\s*name)?|name|particulars?|"
    r"qty|quantity|accepted|recd\s*qty|po\s*qty|ordered|"
    r"unit\s*price|amount|rate|uom|sku|hs\s*code|"
    r"country\s*of\s*origin|net\s*weight|gross\s*weight)\s*:?\s*$",
    re.I,
)


def qty_header_rank(header: str) -> int | None:
    """Return qty preference rank (lower is better), or None if not a qty header."""
    text = (header or "").strip()
    if not text:
        return None
    if UNIT_PRICE_HEADER_RE.search(text):
        return None
    best: int | None = None
    for rank, pattern in QTY_HEADER_RANK:
        if pattern.search(text):
            best = rank if best is None else min(best, rank)
    return best


def select_best_qty_column(headers_by_col: dict[int, str]) -> int:
    """Pick qty column by rank; ties keep the left-most column."""
    best_col = -1
    best_rank: int | None = None
    for col in sorted(headers_by_col):
        rank = qty_header_rank(headers_by_col[col])
        if rank is None:
            continue
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_col = col
    return best_col


def is_tax_column_header(header: str) -> bool:
    text = (header or "").strip()
    if not text:
        return False
    if re.search(r"ex\s*gst|excl|incl", text, re.I):
        return False
    return bool(TAX_HEADER_RE.search(text))


def is_unit_price_column_header(header: str) -> bool:
    text = (header or "").strip()
    if not text:
        return False
    if re.search(r"amount|total|extended|line\s*total", text, re.I):
        return False
    return bool(UNIT_PRICE_HEADER_RE.search(text))


def is_amount_column_header(header: str) -> bool:
    text = (header or "").strip()
    if not text:
        return False
    if AMOUNT_FOOTER_HEADER_RE.search(text):
        return False
    return bool(AMOUNT_HEADER_RE.search(text))


def prefers_amount_header(header: str) -> bool:
    return bool(re.search(r"amount|extended|line\s*total|value|ex\s*gst", header or "", re.I))


def vertical_header_role(line: str) -> str | None:
    """Map a single vertical OCR header cell to a role name."""
    token = (line or "").strip()
    if not token:
        return None
    if VERTICAL_SKIP_HEADER_RE.match(token):
        return "skip"
    if VERTICAL_DESC_HEADER_RE.match(token):
        return "description"
    if VERTICAL_QTY_HEADER_RE.match(token):
        return "qty"
    if VERTICAL_TAX_HEADER_RE.match(token):
        return "tax"
    if VERTICAL_UNIT_PRICE_HEADER_RE.match(token):
        return "unit_price"
    if VERTICAL_AMOUNT_HEADER_RE.match(token):
        return "amount"
    return None
