"""Application-level line-item extraction policy (source ranking + document shape).

Regex/header vocab remain thin helpers. This module decides *what kinds of
sources are allowed* and *which tier wins* so sample-specific fallback bleed
cannot silently invent product rows on money invoices.
"""

from __future__ import annotations

from enum import Enum

from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem

# Tier priority: lower wins. Payload DI/layout and PDF geometry outrank OCR text scrape.
PRIORITY_PAYLOAD = 10
PRIORITY_PDF_SPARSE = 15  # vision / empty OCR — native PDF tables are authoritative
PRIORITY_PDF = 25
PRIORITY_TEXT_MONEY = 40
PRIORITY_GRN_QTY = 50
PRIORITY_TEXT_QTY = 60

SPARSE_OCR_PROVIDERS = frozenset({"vision_dt_scoped", "vision_header", "vision_type_suggest"})


class LineDocumentShape(str, Enum):
    MONEY = "money"
    QTY_ONLY = "qty_only"
    CHARGE = "charge"
    UNKNOWN = "unknown"


def is_sparse_ocr_payload(payload: dict[str, object] | None) -> bool:
    """True when OCR is a vision stub without DI/layout tables."""
    data = payload or {}
    provider = str(data.get("provider") or data.get("di_model") or "").strip().lower()
    if provider in SPARSE_OCR_PROVIDERS:
        return True
    has_di = bool(data.get("di_line_items"))
    has_table = bool(data.get("table_line_items")) or bool(data.get("layout_table_grids"))
    text_len = data.get("text_length")
    if isinstance(text_len, int) and text_len <= 0 and not has_di and not has_table:
        return True
    return False


def money_bearing_rows(rows: list[ParsedLineItem]) -> list[ParsedLineItem]:
    return [row for row in rows if row.amount is not None or row.unit_price is not None]


def qty_bearing_rows(rows: list[ParsedLineItem]) -> list[ParsedLineItem]:
    return [row for row in rows if row.qty is not None and (row.description or "").strip()]


def document_requires_line_items(dt_definition: object | None) -> bool:
    """True when the mapped DT lists line_items as an extraction / playbook field."""
    if dt_definition is None:
        return False

    def _keys_from(raw: object | None) -> set[str]:
        if not isinstance(raw, (list, tuple)):
            return set()
        return {str(k).strip().lower() for k in raw if str(k).strip()}

    keys: set[str] = set()
    for attr in (
        "extraction_fields",
        "required_fields",
        "compulsory_fields",
        "playbook_required_fields",
    ):
        keys |= _keys_from(getattr(dt_definition, attr, None))

    try:
        from app.services.classification.document_type_playbook_service import (
            effective_extraction_fields,
            effective_playbook_required_fields,
        )

        keys.update(str(k).strip().lower() for k in effective_extraction_fields(dt_definition))
        keys.update(str(k).strip().lower() for k in effective_playbook_required_fields(dt_definition))
    except Exception:
        pass
    return "line_items" in keys


def team_expense_hard_requires_line_items(
    dt_definition: object | None,
    *,
    team_expense_kind: str | None = None,
) -> bool:
    """Advance requisitions post from header total — not line grids.

    Generic expense claims may still list line_items on the DT for enrichment,
    but missing rows must not block understood-path posting for advances.
    """
    from app.schemas.rule_book_config import (
        TEAM_EXPENSE_KIND_ADVANCE,
        normalize_team_expense_kind,
    )
    from app.services.classification.document_type_catalog import (
        is_team_expenses_document_type,
    )
    from app.services.purchase.team_expense_kind_service import (
        document_type_team_expense_kind,
    )

    if not is_team_expenses_document_type(dt_definition):  # type: ignore[arg-type]
        return document_requires_line_items(dt_definition)

    pinned = document_type_team_expense_kind(dt_definition)  # type: ignore[arg-type]
    kind = normalize_team_expense_kind(team_expense_kind or pinned)
    if kind == TEAM_EXPENSE_KIND_ADVANCE:
        return False
    return document_requires_line_items(dt_definition)


def classify_line_document_shape(
    text: str,
    payload: dict[str, object] | None,
    *,
    dt_definition: object | None = None,
    parsed: InvoiceData | None = None,
) -> LineDocumentShape:
    """Classify whether this document expects money product rows, qty-only, or charges."""
    from app.services.extraction.line_items_parser import (
        document_has_charge_lines,
        document_has_qty_only_table,
        text_has_money_product_signals,
    )

    blob = (text or "").strip()
    payload_dict = payload or {}
    bundle_role = ""
    if dt_definition is not None:
        bundle_role = str(getattr(dt_definition, "purchase_bundle_role", "") or "").strip().lower()

    if bundle_role == "grn":
        return LineDocumentShape.QTY_ONLY

    if text_has_money_product_signals(blob):
        return LineDocumentShape.MONEY

    # Header totals on InvoiceData imply a money document even when OCR is sparse.
    if parsed is not None and (
        parsed.total is not None or parsed.subtotal is not None or parsed.gst is not None
    ):
        if not document_has_qty_only_table(blob, payload_dict):
            return LineDocumentShape.MONEY

    structured_money = False
    try:
        from app.services.extraction.line_items_parser import (
            resolve_usable_line_items_from_payload,
        )

        structured = resolve_usable_line_items_from_payload(payload_dict, allow_qty_only=True)
        structured_money = bool(money_bearing_rows(structured))
    except Exception:
        structured_money = False
    if structured_money:
        return LineDocumentShape.MONEY

    if document_has_qty_only_table(blob, payload_dict):
        return LineDocumentShape.QTY_ONLY

    if document_has_charge_lines(blob):
        return LineDocumentShape.CHARGE

    return LineDocumentShape.UNKNOWN


def filter_rows_for_shape(
    rows: list[ParsedLineItem],
    shape: LineDocumentShape,
) -> list[ParsedLineItem]:
    """Drop rows that are illegal for the document shape (e.g. address qty bleed)."""
    if not rows:
        return []
    if shape == LineDocumentShape.MONEY:
        return money_bearing_rows(rows)
    if shape == LineDocumentShape.QTY_ONLY:
        return qty_bearing_rows(rows)
    if shape == LineDocumentShape.CHARGE:
        return money_bearing_rows(rows) or qty_bearing_rows(rows)
    # UNKNOWN: prefer money rows when any exist; otherwise keep qty product rows.
    money = money_bearing_rows(rows)
    return money if money else qty_bearing_rows(rows)


def pick_best_fallback_tier(
    candidates: list[tuple[str, list[ParsedLineItem], int]],
) -> tuple[str, list[ParsedLineItem]] | None:
    """Select the winning fallback tier by priority, then by usable row count."""
    usable = [(name, rows, priority) for name, rows, priority in candidates if rows]
    if not usable:
        return None
    usable.sort(key=lambda item: (item[2], -len(item[1])))
    name, rows, _ = usable[0]
    return name, rows


def line_items_extraction_incomplete(
    *,
    wants_line_items: bool,
    rows: list[ParsedLineItem] | None,
    shape: LineDocumentShape | None = None,
) -> bool:
    """True when DT requires lines and none usable remain after ranked extraction."""
    if not wants_line_items:
        return False
    items = list(rows or [])
    if shape == LineDocumentShape.MONEY:
        return not money_bearing_rows(items)
    if shape == LineDocumentShape.QTY_ONLY:
        return not qty_bearing_rows(items)
    return len(items) == 0
