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

_MONEY_TOKEN = rf"{OPTIONAL_CURRENCY_MONEY_PREFIX}([\d,]+\.?\d*)"
_TAIL_ROW_5 = re.compile(
    rf"(\d+(?:\.\d+)?)\s+{_MONEY_TOKEN}\s+{_MONEY_TOKEN}\s+{_MONEY_TOKEN}\s*$",
    re.I,
)
_TAIL_ROW_4 = re.compile(
    rf"(\d+(?:\.\d+)?)\s+{_MONEY_TOKEN}\s+{_MONEY_TOKEN}\s*$",
    re.I,
)
_MONTH_TRAIL = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*$",
    re.I,
)
_TABLE_HEADER_LINE = re.compile(
    r"^(?:description|item|product|qty|quantity|unit\s*price|amount|gst|tax|rate|uom|sku)\b",
    re.I,
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


def _looks_like_money_token(token: str) -> bool:
    cleaned = token.strip()
    if not cleaned:
        return False
    if re.match(rf"^{OPTIONAL_CURRENCY_MONEY_PREFIX}[\d,]+\.?\d*\s*$", cleaned, re.I):
        return True
    return bool(re.match(r"^[\d,]+\.\d{2}$", cleaned))


def _qty_looks_like_year_in_description(item: ParsedLineItem) -> bool:
    qty = item.qty
    desc = (item.description or "").strip()
    if qty is None or not desc:
        return False
    if qty != qty.to_integral_value():
        return False
    year = int(qty)
    if not (1900 <= year <= 2099):
        return False
    return bool(_MONTH_TRAIL.search(desc))


def _repair_year_misplaced_as_qty(item: ParsedLineItem) -> ParsedLineItem:
    if not _qty_looks_like_year_in_description(item):
        return item
    year = int(item.qty)
    desc = (item.description or "").strip()
    repaired_desc = desc if desc.endswith(str(year)) else f"{desc} {year}"
    return ParsedLineItem(
        description=repaired_desc,
        qty=Decimal("1") if item.unit_price is not None or item.amount is not None else None,
        unit_price=item.unit_price,
        amount=item.amount,
        tax_amount=item.tax_amount,
    )


def _line_item_row_score(item: ParsedLineItem) -> tuple[int, int, int, int]:
    score = 0
    if _qty_looks_like_year_in_description(item):
        score -= 10
    elif item.qty is not None and item.qty > Decimal("10000"):
        score -= 5
    money_signal = 0
    if item.unit_price is not None or item.amount is not None:
        score += 1
        for value in (item.unit_price, item.amount):
            if value is not None:
                money_signal = max(money_signal, int(value))
    return (score, money_signal, 1 if item.qty is not None else 0, len(item.description or ""))


def _dedupe_prefix_fragment_rows(items: list[ParsedLineItem]) -> list[ParsedLineItem]:
    if len(items) < 2:
        return items
    keep = [True] * len(items)
    for i, left in enumerate(items):
        if not keep[i]:
            continue
        left_key = _normalize_line_description(left.description)
        if not left_key:
            continue
        for j in range(i + 1, len(items)):
            if not keep[j]:
                continue
            right = items[j]
            right_key = _normalize_line_description(right.description)
            if not right_key:
                continue
            if left_key != right_key and not (left_key.startswith(right_key) or right_key.startswith(left_key)):
                continue
            if _line_item_row_score(left) >= _line_item_row_score(right):
                keep[j] = False
            else:
                keep[i] = False
                break
    return [item for item, kept in zip(items, keep) if kept]


def _parse_table_row_tail(line: str) -> ParsedLineItem | None:
    """Parse one OCR table row by anchoring qty and money columns at the line end."""
    raw = line.strip()
    if not raw or len(raw) < 8 or _TABLE_HEADER_LINE.match(raw):
        return None

    cols = [part.strip() for part in re.split(r"\s{2,}|\t+", raw) if part.strip()]
    if len(cols) >= 4 and not _looks_like_money_token(cols[1]):
        desc = cols[0]
        if _skip_line_row(desc):
            return None
        if len(cols) >= 5:
            return ParsedLineItem(
                description=desc,
                qty=_qty(cols[1]),
                unit_price=_money(cols[2]),
                tax_amount=_money(cols[3]),
                amount=_money(cols[4]),
            )
        return ParsedLineItem(
            description=desc,
            qty=_qty(cols[1]),
            unit_price=_money(cols[2]),
            amount=_money(cols[3]),
        )

    for pattern, with_gst in ((_TAIL_ROW_5, True), (_TAIL_ROW_4, False)):
        match = pattern.search(raw)
        if not match:
            continue
        desc = raw[: match.start()].strip()
        if len(desc) < 4 or _skip_line_row(desc):
            continue
        groups = match.groups()
        if with_gst:
            return ParsedLineItem(
                description=desc,
                qty=_qty(groups[0]),
                unit_price=_money(groups[1]),
                tax_amount=_money(groups[2]),
                amount=_money(groups[3]),
            )
        return ParsedLineItem(
            description=desc,
            qty=_qty(groups[0]),
            unit_price=_money(groups[1]),
            amount=_money(groups[2]),
        )
    return None


def _parse_row_for_description(text: str, description: str) -> ParsedLineItem | None:
    needle = re.sub(r"\s+", " ", (description or "").strip())
    if not needle or _skip_line_row(needle):
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or needle.lower() not in line.lower():
            continue
        parsed = _parse_table_row_tail(line)
        if parsed is None:
            continue
        parsed_desc = parsed.description or ""
        if not (
            parsed_desc.lower().startswith(needle.lower()[: min(len(needle), 24)])
            or needle.lower().startswith(parsed_desc.lower()[: min(len(parsed_desc), 24)])
        ):
            continue
        return ParsedLineItem(
            description=needle if len(needle) >= len(parsed_desc) else parsed.description,
            qty=parsed.qty,
            unit_price=parsed.unit_price,
            amount=parsed.amount,
            tax_amount=parsed.tax_amount,
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
    for raw_line in text.splitlines():
        parsed = _parse_table_row_tail(raw_line)
        if parsed is not None:
            items.append(parsed)
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
    repaired = [_repair_year_misplaced_as_qty(item) for item in items]
    deduped = _dedupe_prefix_fragment_rows(repaired)
    enriched: list[ParsedLineItem] = []
    for item in deduped:
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
