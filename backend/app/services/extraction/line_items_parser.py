"""Extract and normalise invoice line items (local text + Azure DI)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.services.extraction.line_item_skip_patterns import (
    OPTIONAL_CURRENCY_MONEY_PREFIX,
    should_skip_line_row,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.shared.amount_sanity import (
    plausible_money,
    plausible_qty,
    sanitize_parsed_line_item,
)

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
def _money(raw: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return plausible_money(Decimal(cleaned))
    except Exception:
        return None


def _qty(raw: str | Decimal | int | float) -> Decimal | None:
    if isinstance(raw, Decimal):
        return plausible_qty(raw)
    try:
        cleaned = re.sub(r"[^\d.]", "", str(raw).replace(",", ""))
        if not cleaned:
            return None
        return plausible_qty(Decimal(cleaned))
    except Exception:
        return None


def _skip_line_row(desc: str) -> bool:
    return should_skip_line_row(desc)


_COLUMN_LINE_ROW = re.compile(
    r"^(.{4,120}?)\s{2,}(\d+(?:\.\d+)?)\s{2,}([\d,]+\.?\d*)\s{2,}([\d,]+\.?\d*)\s*$",
    re.M,
)


def _parse_row_for_description(text: str, description: str) -> ParsedLineItem | None:
    needle = re.sub(r"\s+", " ", (description or "").strip())
    if not needle or _skip_line_row(needle):
        return None
    escaped = re.escape(needle)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or needle.lower() not in line.lower():
            continue

        cols = [part.strip() for part in re.split(r"\s{2,}|\t+", line) if part.strip()]
        if len(cols) >= 4 and cols[0].lower().startswith(needle.lower()[: min(len(needle), 20)]):
            try:
                qty = _qty(cols[1])
            except Exception:
                qty = None
            return ParsedLineItem(
                description=cols[0],
                qty=qty,
                unit_price=_money(cols[2]),
                amount=_money(cols[3]),
            )

        m = re.search(
            rf"{escaped}\s+(\d+(?:\.\d+)?)\s+{OPTIONAL_CURRENCY_MONEY_PREFIX}([\d,]+\.?\d*)\s+{OPTIONAL_CURRENCY_MONEY_PREFIX}([\d,]+\.?\d*)",
            line,
            re.I,
        )
        if m:
            return ParsedLineItem(
                description=needle,
                qty=_qty(m.group(1)),
                unit_price=_money(m.group(2)),
                amount=_money(m.group(3)),
            )
    return None


def enrich_line_items_from_text(
    items: list[ParsedLineItem],
    text: str,
) -> list[ParsedLineItem]:
    """Fill missing qty/unit/amount on existing rows from OCR text."""
    if not text.strip() or not items:
        return items

    enriched: list[ParsedLineItem] = []
    for item in items:
        if _skip_line_row(item.description or ""):
            continue
        parsed = _parse_row_for_description(text, item.description or "")
        if parsed is None:
            enriched.append(item)
            continue
        enriched.append(
            ParsedLineItem(
                description=item.description or parsed.description,
                qty=item.qty if item.qty is not None else parsed.qty,
                unit_price=item.unit_price if item.unit_price is not None else parsed.unit_price,
                amount=item.amount if item.amount is not None else parsed.amount,
                tax_amount=item.tax_amount,
            )
        )
    return enrich_parsed_line_items(enriched)


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
                qty=_qty(qty_s),
                unit_price=_money(unit_s),
                amount=_money(amt_s),
            )
        )
    if items:
        return enrich_parsed_line_items(items)

    for m in _COLUMN_LINE_ROW.finditer(text):
        desc, qty_s, unit_s, amt_s = m.groups()
        if _skip_line_row(desc):
            continue
        items.append(
            ParsedLineItem(
                description=desc.strip(),
                qty=_qty(qty_s),
                unit_price=_money(unit_s),
                amount=_money(amt_s),
            )
        )
    if items:
        return enrich_parsed_line_items(items)

    for m in _GRN_LINE_ROW.finditer(text):
        desc, qty_s = m.groups()
        if _skip_line_row(desc) or re.search(r"qty\s*received|condition", desc, re.I):
            continue
        items.append(
            ParsedLineItem(
                description=desc.strip(),
                qty=_qty(qty_s),
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
        qty = _qty(qty_match[1]) if len(qty_match) >= 2 else (
            _qty(qty_match[0]) if qty_match else None
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
        unit = _line_prop(item, "UnitPrice")
        amount = _line_prop(item, "Amount")
        tax = _line_prop(item, "Tax")

        description = str(desc).strip() if desc else None
        if not description or _skip_line_row(description):
            continue
        parsed.append(
            ParsedLineItem(
                description=description,
                qty=_qty(qty) if qty is not None else None,
                unit_price=_money(str(unit)) if unit is not None else None,
                amount=_money(str(amount)) if amount is not None else None,
                tax_amount=_money(str(tax)) if tax is not None else None,
            )
        )
    return parsed


def _normalize_line_description(desc: str | None) -> str:
    return re.sub(r"\s+", " ", (desc or "").strip().lower())


def enrich_parsed_line_items(items: list[ParsedLineItem]) -> list[ParsedLineItem]:
    enriched: list[ParsedLineItem] = []
    for item in items:
        qty = item.qty
        unit_price = item.unit_price
        amount = item.amount
        if amount is None and qty is not None and unit_price is not None:
            amount = qty * unit_price
        if unit_price is None and amount is not None and qty is not None and qty > 0:
            unit_price = amount / qty
        enriched.append(sanitize_parsed_line_item(
            ParsedLineItem(
                description=item.description,
                qty=qty,
                unit_price=unit_price,
                amount=amount,
                tax_amount=item.tax_amount,
            )
        ))
    return enriched


def merge_line_item_lists(
    primary: list[ParsedLineItem],
    secondary: list[ParsedLineItem],
) -> list[ParsedLineItem]:
    """Fill gaps in primary line rows from a secondary source (text/tables/DI)."""
    if not secondary:
        return enrich_parsed_line_items(list(primary))
    if not primary:
        return enrich_parsed_line_items(list(secondary))

    secondary_by_desc = {
        _normalize_line_description(item.description): item
        for item in secondary
        if _normalize_line_description(item.description)
    }
    merged: list[ParsedLineItem] = []
    used_secondary: set[str] = set()

    for index, primary_item in enumerate(primary):
        key = _normalize_line_description(primary_item.description)
        secondary_item = secondary_by_desc.get(key) if key else None
        if secondary_item is None and index < len(secondary):
            secondary_item = secondary[index]
        if secondary_item and key:
            used_secondary.add(key)

        if secondary_item is None:
            merged.append(primary_item)
            continue

        merged.append(
            ParsedLineItem(
                description=primary_item.description or secondary_item.description,
                qty=primary_item.qty if primary_item.qty is not None else secondary_item.qty,
                unit_price=(
                    primary_item.unit_price
                    if primary_item.unit_price is not None
                    else secondary_item.unit_price
                ),
                amount=(
                    primary_item.amount
                    if primary_item.amount is not None
                    else secondary_item.amount
                ),
                tax_amount=primary_item.tax_amount or secondary_item.tax_amount,
            )
        )

    for secondary_item in secondary:
        key = _normalize_line_description(secondary_item.description)
        if key and key in used_secondary:
            continue
        if not key and len(merged) >= len(secondary):
            continue
        merged.append(secondary_item)

    return enrich_parsed_line_items(merged)


def serialize_line_items(items: list[ParsedLineItem]) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for item in items:
        rows.append(
            {
                "description": item.description,
                "qty": str(item.qty) if item.qty is not None else None,
                "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                "amount": str(item.amount) if item.amount is not None else None,
            }
        )
    return rows


def deserialize_line_items(raw: object) -> list[ParsedLineItem]:
    if not isinstance(raw, list):
        return []
    items: list[ParsedLineItem] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        description = str(row.get("description") or "").strip() or None
        qty_raw = row.get("qty")
        unit_raw = row.get("unit_price")
        amount_raw = row.get("amount")
        qty = None
        if qty_raw is not None and str(qty_raw).strip():
            try:
                qty = _qty(str(qty_raw).replace(",", ""))
            except Exception:
                qty = None
        items.append(
            ParsedLineItem(
                description=description,
                qty=qty,
                unit_price=_money(str(unit_raw)) if unit_raw is not None else None,
                amount=_money(str(amount_raw)) if amount_raw is not None else None,
            )
        )
    return items


def line_items_from_ocr_payload(payload: dict[str, object]) -> list[ParsedLineItem]:
    items: list[ParsedLineItem] = []
    for key in ("di_line_items", "table_line_items", "line_items"):
        items.extend(deserialize_line_items(payload.get(key)))
    return items


def ensure_line_items(data: InvoiceData) -> None:
    """Guarantee at least one line when header amounts exist (brief §3)."""
    if data.line_items:
        return
    if data.subtotal is None:
        return
    data.line_items.append(
        sanitize_parsed_line_item(
            ParsedLineItem(
                description="General charges",
                qty=Decimal("1"),
                unit_price=data.subtotal,
                amount=data.subtotal,
                tax_amount=data.gst,
            )
        )
    )
