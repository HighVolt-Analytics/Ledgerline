"""Extract and normalise invoice line items (local text + Azure DI)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Sequence

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


def _line_item_row_usable(item: ParsedLineItem, *, allow_qty_only: bool = False) -> bool:
    from app.services.extraction.line_items_sanitizer import _passes_minimum_product_row

    return _passes_minimum_product_row(item, allow_qty_only=allow_qty_only)


def _usable_line_items(
    items: Sequence[ParsedLineItem],
    *,
    allow_qty_only: bool = False,
) -> list[ParsedLineItem]:
    return [item for item in items if _line_item_row_usable(item, allow_qty_only=allow_qty_only)]


def di_line_items_usable(payload: dict[str, object] | None) -> bool:
    """True when deserialized DI rows contain at least one product row."""
    if not payload:
        return False
    return len(_usable_line_items(deserialize_line_items(payload.get("di_line_items")))) >= 1


def table_line_items_usable(
    payload: dict[str, object] | None,
    *,
    allow_qty_only: bool = False,
) -> bool:
    """True when layout table rows contain at least one usable product row."""
    if not payload:
        return False
    rows = deserialize_line_items(payload.get("table_line_items"))
    if not rows:
        return False
    if allow_qty_only:
        return len(_usable_line_items(rows, allow_qty_only=True)) >= 1
    money_rows = [
        item
        for item in rows
        if item.amount is not None or item.unit_price is not None
    ]
    if len(_usable_line_items(money_rows)) >= 1:
        return True
    return len(_usable_line_items(rows, allow_qty_only=False)) >= 1


def resolve_usable_line_items_from_payload(
    payload: dict[str, object] | None,
    *,
    allow_qty_only: bool = False,
) -> list[ParsedLineItem]:
    """Prefer usable DI rows; fall back to usable layout table rows."""
    if not payload:
        return []
    di_items = _usable_line_items(deserialize_line_items(payload.get("di_line_items")))
    if di_items:
        return enrich_parsed_line_items(di_items)
    table_items = deserialize_line_items(payload.get("table_line_items"))
    if allow_qty_only:
        usable = _usable_line_items(table_items, allow_qty_only=True)
    else:
        money_rows = [
            item
            for item in table_items
            if item.amount is not None or item.unit_price is not None
        ]
        usable = _usable_line_items(money_rows) or _usable_line_items(table_items)
    if usable:
        return enrich_parsed_line_items(usable)
    return []


def resolve_line_items_from_ocr_payload(payload: dict[str, object] | None) -> list[ParsedLineItem] | None:
    """Prefer prebuilt-invoice rows; fall back to layout table rows."""
    usable = resolve_usable_line_items_from_payload(payload)
    return usable if usable else None


_QTY_HEADER_PATTERN = re.compile(r"(?:qty|quantity|q'?ty|pcs)\b", re.I)
_DESC_HEADER_PATTERN = re.compile(
    r"(?:desc|item|product|part|component|model|cpu|service)\b",
    re.I,
)
_MONEY_HEADER_PATTERN = re.compile(
    r"(?:unit\s*price|rate|amount|line\s*total|extended|value|ex\s*gst|unit\s*cost|(?:^|\s)each(?:\s|$)|^price$|\bprice\b)",
    re.I,
)
_TOTALS_LABEL = re.compile(r"^\s*(?:TOTALS?|GRAND\s+TOTAL|SUB\s*TOTAL)\b", re.I)
_FOOTER_TOTALS_LINE = re.compile(
    r"(?:total\s+net\s+weight|total\s+gross\s+weight|total\s+no\.?\s+of\s+pallet)",
    re.I,
)
_QTY_ONLY_TAIL = re.compile(
    r"^(.+?)\s+(\d+(?:\.\d+)?)\s*(?:pcs|nos|units?|kg)?\s*$",
    re.I,
)


def _split_table_columns(line: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\s{2,}|\t+", line.strip()) if part.strip()]
    if len(parts) >= 2:
        return parts
    return [part.strip() for part in line.strip().split() if part.strip()]


def _table_has_money_columns(headers: Sequence[str]) -> bool:
    for header in headers:
        lowered = header.lower()
        if re.search(r"subtotal|grand", lowered):
            continue
        if _MONEY_HEADER_PATTERN.search(lowered):
            return True
    return False


def _table_has_qty_column(headers: Sequence[str]) -> bool:
    return any(_QTY_HEADER_PATTERN.search(header) for header in headers)


def _table_has_description_column(headers: Sequence[str]) -> bool:
    return any(_DESC_HEADER_PATTERN.search(header) for header in headers)


def _is_qty_only_totals_line(text: str, cells: Sequence[str] | None = None) -> bool:
    from app.services.extraction.line_item_skip_patterns import is_summary_line_description

    if is_summary_line_description(text):
        return True
    if _TOTALS_LABEL.search(text.strip()):
        return True
    if _FOOTER_TOTALS_LINE.search(text):
        return True
    if cells:
        for cell in cells:
            token = cell.strip()
            if token and (_TOTALS_LABEL.search(token) or is_summary_line_description(token)):
                return True
    return False


def _is_aggregate_qty_row(qty: Decimal | None, prior_qtys: Sequence[Decimal]) -> bool:
    if qty is None or not prior_qtys:
        return False
    return qty == sum(prior_qtys)


def _payload_has_qty_only_table_rows(payload: dict[str, object]) -> bool:
    rows = payload.get("table_line_items")
    if not isinstance(rows, list) or not rows:
        return False
    saw_qty_row = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        desc = str(row.get("description") or "").strip()
        qty = row.get("qty")
        amount = row.get("amount")
        unit_price = row.get("unit_price")
        if amount or unit_price:
            return False
        if desc and qty and not _is_qty_only_totals_line(desc):
            saw_qty_row = True
    return saw_qty_row


def _find_qty_only_header_line(text: str) -> tuple[int, list[str]] | None:
    for index, line in enumerate(text.splitlines()):
        cols = _split_table_columns(line)
        if len(cols) < 2:
            continue
        lowered = [col.lower() for col in cols]
        if (
            _table_has_qty_column(lowered)
            and _table_has_description_column(lowered)
            and not _table_has_money_columns(lowered)
        ):
            return index, cols
    return None


def _find_qty_column_index(cols: Sequence[str]) -> int | None:
    for index in range(len(cols) - 1, -1, -1):
        token = cols[index].strip()
        if re.match(r"^\d+\s*(?:pcs|nos|units?|kg)?$", token, re.I):
            return index
        if re.match(r"^\d+$", token):
            return index
    return None


def _parse_qty_only_row(line: str) -> ParsedLineItem | None:
    """Parse one OCR row with description + qty and no trailing money columns."""
    raw = line.strip()
    if not raw or len(raw) < 4 or _TABLE_HEADER_LINE.match(raw):
        return None
    if _is_qty_only_totals_line(raw):
        return None

    tail_parsed = _parse_table_row_tail(raw)
    if tail_parsed is not None and (
        tail_parsed.unit_price is not None or tail_parsed.amount is not None
    ):
        return None

    cols = _split_table_columns(raw)
    if len(cols) >= 2:
        qty_index = _find_qty_column_index(cols)
        if qty_index is not None and qty_index > 0:
            desc = " ".join(cols[:qty_index]).strip()
            qty_token = cols[qty_index]
            if len(desc) >= 3 and not _skip_line_row(desc) and not _is_qty_only_totals_line(desc, cols):
                qty = _qty(re.sub(r"[^\d.]", "", qty_token))
                if qty is not None:
                    return ParsedLineItem(description=desc, qty=qty, unit_price=None, amount=None)
        for qty_index in range(len(cols) - 1, 0, -1):
            qty_token = cols[qty_index]
            if not re.match(r"^\d+(?:\.\d+)?\s*(?:pcs|nos|units?|kg)?$", qty_token, re.I):
                continue
            if _looks_like_money_token(qty_token):
                continue
            desc = " ".join(cols[:qty_index]).strip()
            if len(desc) < 3 or _skip_line_row(desc) or _is_qty_only_totals_line(desc, cols):
                continue
            qty = _qty(re.sub(r"[^\d.]", "", qty_token))
            if qty is None:
                continue
            return ParsedLineItem(description=desc, qty=qty, unit_price=None, amount=None)

    match = _QTY_ONLY_TAIL.match(raw)
    if not match:
        return None
    desc = match.group(1).strip()
    if len(desc) < 3 or _skip_line_row(desc) or _is_qty_only_totals_line(desc):
        return None
    qty = _qty(match.group(2))
    if qty is None:
        return None
    return ParsedLineItem(description=desc, qty=qty, unit_price=None, amount=None)


def parse_qty_only_line_items_from_text(text: str) -> list[ParsedLineItem]:
    """Extract qty-only product rows from OCR text (packing lists, challans, etc.)."""
    body = (text or "").strip()
    if not body:
        return []

    lines = body.splitlines()
    header_info = _find_qty_only_header_line(body)
    header_cols: list[str] = []
    qty_col = -1
    desc_start = 0
    start_row = 0
    if header_info is not None:
        header_index, header_cols = header_info
        start_row = header_index + 1
        for index, header in enumerate(header_cols):
            lowered = header.lower()
            if _QTY_HEADER_PATTERN.search(lowered):
                qty_col = index
            if _DESC_HEADER_PATTERN.search(lowered) and desc_start == 0:
                desc_start = index

    items: list[ParsedLineItem] = []
    prior_qtys: list[Decimal] = []
    for line in lines[start_row:]:
        raw = line.strip()
        if not raw:
            prior_qtys = []
            continue
        if _is_qty_only_totals_line(raw):
            continue

        parsed: ParsedLineItem | None = None
        cols = _split_table_columns(raw)
        if header_cols and qty_col >= 0 and len(cols) == len(header_cols) and len(cols) > qty_col:
            desc_parts: list[str] = []
            for index, header in enumerate(header_cols):
                if index == qty_col:
                    break
                lowered = header.lower()
                if _DESC_HEADER_PATTERN.search(lowered) or re.search(
                    r"part|component|model|cpu", lowered
                ):
                    token = cols[index].strip()
                    if token:
                        desc_parts.append(token)
            desc = " ".join(desc_parts) or cols[0]
            qty = _qty(re.sub(r"[^\d.]", "", cols[qty_col]))
            if desc and qty is not None and not _is_qty_only_totals_line(desc, cols):
                if not _is_aggregate_qty_row(qty, prior_qtys):
                    parsed = ParsedLineItem(description=desc, qty=qty, unit_price=None, amount=None)
        if parsed is None:
            parsed = _parse_qty_only_row(raw)
        if parsed is None or _skip_line_row(parsed.description or ""):
            continue
        if parsed.qty is not None and _is_aggregate_qty_row(parsed.qty, prior_qtys):
            continue
        items.append(parsed)
        if parsed.qty is not None:
            prior_qtys.append(parsed.qty)

    return enrich_parsed_line_items(items)


def document_has_qty_only_table(
    ocr_text: str | None,
    payload: dict[str, object] | None,
) -> bool:
    """True when OCR/layout shows a qty table without money columns."""
    payload_dict = payload or {}
    if di_line_items_usable(payload_dict):
        return False
    if _payload_has_qty_only_table_rows(payload_dict):
        return True

    table_items = deserialize_line_items(payload_dict.get("table_line_items"))
    if table_items and not any(item.amount or item.unit_price for item in table_items):
        if any(item.qty and item.description for item in table_items):
            return True

    text = (ocr_text or "").strip()
    if not text:
        return False
    if _find_qty_only_header_line(text) is not None:
        return len(parse_qty_only_line_items_from_text(text)) >= 1
    qty_rows = [_parse_qty_only_row(line) for line in text.splitlines()]
    parsed_rows = [row for row in qty_rows if row is not None]
    return len(parsed_rows) >= 1


def document_has_line_item_table(
    ocr_text: str | None,
    payload: dict[str, object] | None,
) -> bool:
    """True when document has either money-column or qty-only line tables."""
    return document_has_product_table(ocr_text, payload) or document_has_qty_only_table(
        ocr_text, payload
    )


def document_has_product_table(
    ocr_text: str | None,
    payload: dict[str, object] | None,
) -> bool:
    """True when DI/table rows exist or OCR shows a money-column product grid."""
    payload_dict = payload or {}
    if di_line_items_usable(payload_dict):
        return True
    table_items = deserialize_line_items(payload_dict.get("table_line_items"))
    if table_items and any(item.amount or item.unit_price for item in table_items):
        if len(_usable_line_items(table_items)) >= 1:
            return True
    if document_has_qty_only_table(ocr_text, payload_dict):
        return False
    text = (ocr_text or "").strip()
    if not text:
        return False
    has_header = any(_TABLE_HEADER_LINE.match(line.strip()) for line in text.splitlines())
    data_rows = [
        parsed
        for line in text.splitlines()
        if (parsed := _parse_table_row_tail(line)) is not None
    ]
    if has_header and data_rows:
        return True
    return len(data_rows) >= 2


_CHARGE_FREIGHT = re.compile(
    r"^\s*FREIGHT\s*[:\-]?\s*(?:USD|AUD|SGD|EUR|GBP)?\s*([\d,]+\.?\d*)",
    re.I | re.M,
)
_CHARGE_GOODS_DESC = re.compile(
    r"DESCRIPTION\s+OF\s+GOODS(?:\s+AND/?\s+OR\s+SERVICES)?\s*[:\-]?\s*(.+)$",
    re.I | re.M,
)
_CHARGE_TOTAL = re.compile(
    r"^\s*TOTAL\s*[:\-]?\s*(?:USD|AUD|SGD|EUR|GBP)?\s*([\d,]+\.?\d*)",
    re.I | re.M,
)


def document_has_charge_lines(ocr_text: str | None) -> bool:
    """True for freight/export charge blocks without a product grid."""
    text = (ocr_text or "").strip()
    if not text:
        return False
    if _CHARGE_FREIGHT.search(text):
        return True
    if _CHARGE_GOODS_DESC.search(text) and (_CHARGE_FREIGHT.search(text) or _CHARGE_TOTAL.search(text)):
        return True
    return False


def parse_charge_lines_from_text(text: str | None) -> list[ParsedLineItem]:
    """Parse freight / goods-description charge rows from commercial invoices."""
    body = (text or "").strip()
    if not body:
        return []
    items: list[ParsedLineItem] = []
    goods = _CHARGE_GOODS_DESC.search(body)
    if goods:
        desc = goods.group(1).strip().rstrip(".,;")
        if desc and len(desc) > 3:
            items.append(
                ParsedLineItem(description=desc[:200], qty=Decimal("1"), unit_price=None, amount=None)
            )
    freight = _CHARGE_FREIGHT.search(body)
    if freight:
        amount = _money(freight.group(1))
        if amount is not None:
            items.append(
                ParsedLineItem(
                    description="Freight",
                    qty=Decimal("1"),
                    unit_price=amount,
                    amount=amount,
                )
            )
    if not items:
        total_match = _CHARGE_TOTAL.search(body)
        if total_match:
            amount = _money(total_match.group(1))
            if amount is not None:
                items.append(
                    ParsedLineItem(
                        description="Total charges",
                        qty=Decimal("1"),
                        unit_price=amount,
                        amount=amount,
                    )
                )
    return enrich_parsed_line_items(items)


def normalize_di_line_items_for_prompt(items: Sequence[ParsedLineItem]) -> list[dict[str, Any]]:
    """Canonical Azure DI rows for LLM user payload (string values as printed)."""
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        rows.append(
            {
                "row_index": index,
                "description": (item.description or "").strip(),
                "qty": str(item.qty) if item.qty is not None else None,
                "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                "amount": str(item.amount) if item.amount is not None else None,
            }
        )
    return rows


def line_items_source_from_payload(payload: dict[str, object] | None) -> str:
    if not payload:
        return "none"
    if di_line_items_usable(payload):
        return "azure_di"
    if table_line_items_usable(payload) or table_line_items_usable(payload, allow_qty_only=True):
        return "azure_layout_table"
    return "none"


def build_line_items_presentation_prompt(
    *,
    di_rows_present: bool,
    ocr_table_present: bool,
    qty_only_table_present: bool = False,
    charge_lines_present: bool = False,
) -> list[str]:
    """Mode-specific LLM rules for line_items (DI copy / OCR table / charge / not applicable)."""
    if di_rows_present:
        return [
            "",
            "LINE ITEMS — AZURE DI (authoritative source):",
            "- ocr.azure_di_line_items is pre-extracted by Azure Document Intelligence; it is the ONLY source for line_items.",
            "- line_items MUST be a row-for-row copy of ocr.azure_di_line_items:",
            "  same row count (line_items_row_count), same row order (row_index ascending),",
            "  same description, qty, unit_price, amount strings — do not reformat, round, or calculate.",
            "- Do NOT add, remove, merge, or split rows.",
            "- Do NOT derive amount from qty × unit_price unless that exact value is in azure_di_line_items.",
            "- Use null for qty, unit_price, or amount when the DI row has no value — never guess.",
            "- field_confidence.line_items: 0.95 when copied from azure_di_line_items; 0.0 when line_items is [].",
        ]
    if qty_only_table_present:
        return [
            "",
            "LINE ITEMS — QTY-ONLY TABLE (no price columns):",
            "- Extract product/component rows from ocr.text_excerpt as line_items[].",
            "- Each row: {{description, qty}}; set unit_price and amount to null when absent.",
            "- Exclude TOTALS, GRAND TOTAL, SUB TOTAL, and footer summary rows.",
            "- Extract only product/component lines — never summary or aggregate rows.",
            "- field_confidence.line_items: per-row confidence; 0.0 when line_items is [].",
        ]
    if ocr_table_present:
        return [
            "",
            "LINE ITEMS — OCR TABLE (no Azure DI rows):",
            "- Extract only from product table rows in ocr.text_excerpt.",
            "- Each row: {{description, qty, unit_price, amount}} — copy verbatim from OCR.",
            "- Never include header labels, party blocks, or summary totals as line items.",
            "- field_confidence.line_items: per-row confidence; 0.0 when line_items is [].",
        ]
    if charge_lines_present:
        return [
            "",
            "LINE ITEMS — CHARGE LINES (commercial/export, no product grid):",
            "- Extract charge rows from ocr.text_excerpt: FREIGHT, DESCRIPTION OF GOODS, labeled totals.",
            "- FREIGHT: USD 400.00 → {{description: \"Freight\", qty: 1, unit_price: 400, amount: 400}}.",
            "- DESCRIPTION OF GOODS block → description row; pair with FREIGHT amount when separate.",
            "- Do not invent rows beyond labeled charge blocks.",
            "- field_confidence.line_items: per-row confidence; 0.0 when line_items is [].",
        ]
    return [
        "",
        "LINE ITEMS — NOT APPLICABLE:",
        "- This document has no product line table. Return line_items: [].",
        "- Do not invent a summary or 'General charges' row.",
        "- field_confidence.line_items: 0.0.",
    ]


def ensure_line_items(data: InvoiceData) -> None:
    """Line items must come from DI or OCR product tables — never synthesize rows."""
    return
