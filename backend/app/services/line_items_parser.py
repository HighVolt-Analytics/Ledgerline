"""Extract and normalise invoice line items (local text + Azure DI)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.services.invoice_data import InvoiceData, ParsedLineItem

_LINE_ROW = re.compile(
    r"^(.{4,80}?)\s+(\d+(?:\.\d+)?)\s+\$?\s*([\d,]+\.?\d*)\s+\$?\s*([\d,]+\.?\d*)\s*$",
    re.M,
)
_GRN_LINE_ROW = re.compile(
    r"^(.{4,80}?)\s+(\d+(?:\.\d+)?)\s+(?:Good|Damaged|Partial|[A-Za-z]{3,})\s*$",
    re.M,
)
_GRN_QTY_TABLE_ROW = re.compile(
    r"^\s*\d+\s+(.+?)\s+\d+(?:\.\d+)?\s+(?:Kg|Nos|Box|Pair|Units?|Ltr|Litre)\s+",
    re.M | re.I,
)
_ABN_ROW = re.compile(r"\babn\b", re.I)


def _money(raw: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _skip_line_row(desc: str) -> bool:
    if re.search(r"sub\s*total|gst|total\s*due|amount\s*due", desc, re.I):
        return True
    if _ABN_ROW.search(desc):
        return True
    return False


def parse_line_items_from_text(text: str) -> list[ParsedLineItem]:
    """Heuristic table rows: description qty unit_price amount (and GRN qty rows)."""
    items: list[ParsedLineItem] = []
    for m in _LINE_ROW.finditer(text):
        desc, qty_s, unit_s, amt_s = m.groups()
        if _skip_line_row(desc):
            continue
        items.append(
            ParsedLineItem(
                description=desc.strip(),
                qty=Decimal(qty_s),
                unit_price=_money(unit_s),
                amount=_money(amt_s),
            )
        )
    if items:
        return items

    for m in _GRN_LINE_ROW.finditer(text):
        desc, qty_s = m.groups()
        if _skip_line_row(desc) or re.search(r"qty\s*received|condition", desc, re.I):
            continue
        items.append(
            ParsedLineItem(
                description=desc.strip(),
                qty=Decimal(qty_s),
                unit_price=None,
                amount=None,
            )
        )
    if items:
        return items

    for m in _GRN_QTY_TABLE_ROW.finditer(text):
        desc = m.group(1).strip()
        if _skip_line_row(desc) or re.search(r"item\s+description|po\s+qty", desc, re.I):
            continue
        qty_match = re.findall(
            r"(\d+(?:\.\d+)?)\s+(?:Kg|Nos|Box|Pair|Units?|Ltr|Litre)\b",
            m.group(0),
            re.I,
        )
        qty = Decimal(qty_match[1]) if len(qty_match) >= 2 else (
            Decimal(qty_match[0]) if qty_match else None
        )
        items.append(
            ParsedLineItem(
                description=desc,
                qty=qty,
                unit_price=None,
                amount=None,
            )
        )
    return items


def parse_line_items_from_di_items(items_field: Any) -> list[ParsedLineItem]:
    """Map Azure DI Items array to ParsedLineItem list."""
    if items_field is None:
        return []

    values = getattr(items_field, "value_array", None) or getattr(
        items_field, "valueArray", None
    )
    if not values:
        return []

    def _field_value(field: Any) -> Any:
        if field is None:
            return None
        for attr in ("value_string", "value_number", "content"):
            val = getattr(field, attr, None)
            if val is not None:
                return val
        currency = getattr(field, "value_currency", None)
        if currency is not None:
            return getattr(currency, "amount", None)
        return None

    def _line_prop(item: Any, name: str) -> Any:
        props = getattr(item, "value_object", None) or getattr(item, "valueObject", None)
        if not props:
            return None
        return _field_value(props.get(name))

    parsed: list[ParsedLineItem] = []
    for item in values:
        desc = _line_prop(item, "Description")
        qty = _line_prop(item, "Quantity")
        unit = _line_prop(item, "UnitPrice") or _line_prop(item, "UnitPrice")
        amount = _line_prop(item, "Amount")
        tax = _line_prop(item, "Tax")

        description = str(desc).strip() if desc else None
        if not description:
            continue
        parsed.append(
            ParsedLineItem(
                description=description,
                qty=Decimal(str(qty)) if qty is not None else None,
                unit_price=_money(str(unit)) if unit is not None else None,
                amount=_money(str(amount)) if amount is not None else None,
                tax_amount=_money(str(tax)) if tax is not None else None,
            )
        )
    return parsed


def ensure_line_items(data: InvoiceData) -> None:
    """Guarantee at least one line when header amounts exist (brief §3)."""
    if data.line_items:
        return
    if data.subtotal is None:
        return
    data.line_items.append(
        ParsedLineItem(
            description="General charges",
            qty=Decimal("1"),
            unit_price=data.subtotal,
            amount=data.subtotal,
            tax_amount=data.gst,
        )
    )
