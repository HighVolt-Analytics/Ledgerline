"""Generic money scalar extraction from layout tables and OCR text."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from app.schemas.document_layout import DocumentLayoutResult
from app.services.extraction.finance_field_labels import (
    MONEY_SCALAR_KEYS,
    build_money_inline_patterns,
    build_money_multiline_regex,
    label_matches_field,
)
from app.services.extraction.line_item_skip_patterns import OPTIONAL_CURRENCY_MONEY_PREFIX
from app.services.shared.amount_sanity import plausible_money

if TYPE_CHECKING:
    from collections.abc import Sequence

_TAIL_WINDOW = 1500
_FOOTER_ROWS = 5
_MONEY_TOKEN = re.compile(
    rf"{OPTIONAL_CURRENCY_MONEY_PREFIX}([\d,]+\.?\d*)",
    re.I,
)


def parse_money_token(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(raw).replace(",", ""))
    if not cleaned:
        return None
    try:
        return plausible_money(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def _scan_region_for_money(
    region: str,
    *,
    keys: Sequence[str] | None = None,
) -> dict[str, Decimal]:
    """Extract money scalars from a text region using registry patterns."""
    body = (region or "").strip()
    if not body:
        return {}
    wanted = [k for k in (keys or MONEY_SCALAR_KEYS) if k != "gst_rate"]
    found: dict[str, Decimal] = {}

    for key in wanted:
        if key in found:
            continue
        for pattern_key, pattern in build_money_inline_patterns():
            if pattern_key != key:
                continue
            match = pattern.search(body)
            if match:
                amount = parse_money_token(match.group(1))
                if amount is not None:
                    found[key] = amount
                    break
        if key in found:
            continue
        multiline = build_money_multiline_regex(key)
        match = multiline.search(body)
        if match:
            amount = parse_money_token(match.group(1))
            if amount is not None:
                found[key] = amount

    return found


def extract_money_scalars_from_text(
    text: str | None,
    *,
    keys: Sequence[str] | None = None,
) -> dict[str, Decimal]:
    """Registry-driven money extraction: tail window first, then full body."""
    body = (text or "").strip()
    if not body:
        return {}
    wanted = list(keys or MONEY_SCALAR_KEYS)
    tail = body[-_TAIL_WINDOW:] if len(body) > _TAIL_WINDOW else body
    found = _scan_region_for_money(tail, keys=wanted)
    if len(found) < len([k for k in wanted if k != "gst_rate"]):
        for key, amount in _scan_region_for_money(body, keys=wanted).items():
            found.setdefault(key, amount)
    return found


def _table_grid(layout_table) -> dict[tuple[int, int], str]:
    return {(cell.row_index, cell.column_index): cell.text for cell in layout_table.cells}


def extract_money_scalars_from_tables(
    layout: DocumentLayoutResult | None,
    *,
    keys: Sequence[str] | None = None,
) -> dict[str, Decimal]:
    """Scan table footer rows for labeled money cells."""
    if layout is None or not layout.tables:
        return {}
    wanted = [k for k in (keys or MONEY_SCALAR_KEYS) if k != "gst_rate"]
    found: dict[str, Decimal] = {}

    for table in layout.tables:
        if table.row_count < 1:
            continue
        grid = _table_grid(table)
        start_row = max(0, table.row_count - _FOOTER_ROWS)
        for row in range(start_row, table.row_count):
            for col in range(table.column_count):
                label = grid.get((row, col), "").strip()
                if not label:
                    continue
                for key in wanted:
                    if key in found:
                        continue
                    if not label_matches_field(label, key):
                        continue
                    for sibling_col in range(table.column_count):
                        if sibling_col == col:
                            continue
                        candidate = grid.get((row, sibling_col), "").strip()
                        amount = parse_money_token(candidate)
                        if amount is not None:
                            found[key] = amount
                            break
                    if key not in found:
                        inline = _MONEY_TOKEN.search(label)
                        if inline:
                            amount = parse_money_token(inline.group(1))
                            if amount is not None:
                                found[key] = amount
            if len(found) == len(wanted):
                break
    return found


def extract_money_scalars_from_payload_tables(
    payload: dict[str, object] | None,
    *,
    keys: Sequence[str] | None = None,
) -> dict[str, Decimal]:
    """Extract money from serialized layout table grids in OCR payload."""
    if not payload:
        return {}
    raw = payload.get("layout_table_grids")
    if not isinstance(raw, list):
        return {}
    wanted = [k for k in (keys or MONEY_SCALAR_KEYS) if k != "gst_rate"]
    found: dict[str, Decimal] = {}

    for table_rows in raw:
        if not isinstance(table_rows, list) or not table_rows:
            continue
        footer = table_rows[-_FOOTER_ROWS:] if len(table_rows) > _FOOTER_ROWS else table_rows
        for row in footer:
            if not isinstance(row, list):
                continue
            cells = [str(c or "").strip() for c in row]
            for index, label in enumerate(cells):
                if not label:
                    continue
                for key in wanted:
                    if key in found:
                        continue
                    if not label_matches_field(label, key):
                        continue
                    for sibling in cells[index + 1 :]:
                        amount = parse_money_token(sibling)
                        if amount is not None:
                            found[key] = amount
                            break
                    if key not in found:
                        inline = _MONEY_TOKEN.search(label)
                        if inline:
                            amount = parse_money_token(inline.group(1))
                            if amount is not None:
                                found[key] = amount
    return found


def serialize_layout_table_grids(layout: DocumentLayoutResult | None) -> list[list[list[str]]]:
    """Serialize layout tables for OCR payload persistence."""
    if layout is None or not layout.tables:
        return []
    grids: list[list[list[str]]] = []
    for table in layout.tables:
        grid = _table_grid(table)
        rows: list[list[str]] = []
        for row in range(table.row_count):
            rows.append([grid.get((row, col), "") for col in range(table.column_count)])
        grids.append(rows)
    return grids
