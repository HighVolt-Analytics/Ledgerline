"""Tests for shared DT-agnostic line-item header vocabulary."""

from app.services.extraction.line_item_header_vocab import (
    qty_header_rank,
    select_best_qty_column,
    vertical_header_role,
)


def test_qty_header_rank_prefers_accepted_over_po_and_generic() -> None:
    assert qty_header_rank("Accepted") == 0
    assert qty_header_rank("Recd Qty") == 1
    assert qty_header_rank("PO Qty") == 2
    assert qty_header_rank("Qty") == 3
    assert qty_header_rank("UNIT PRICE") is None


def test_select_best_qty_column_is_rank_not_column_order() -> None:
    # Accepted is leftmost — must still win over later PO Qty / Qty.
    assert select_best_qty_column({0: "Accepted", 1: "PO Qty", 2: "Qty"}) == 0
    # Accepted rightmost — still wins.
    assert select_best_qty_column({0: "PO Qty", 1: "Recd Qty", 2: "Accepted"}) == 2
    # No accepted: received beats ordered/generic.
    assert select_best_qty_column({0: "Qty", 1: "Recd Qty", 2: "PO Qty"}) == 1


def test_vertical_header_roles_cover_po_and_tax_synonyms() -> None:
    assert vertical_header_role("Name") == "description"
    assert vertical_header_role("PO Qty") == "qty"
    assert vertical_header_role("Ordered") == "qty"
    assert vertical_header_role("CGST") == "tax"
    assert vertical_header_role("IGST") == "tax"
    assert vertical_header_role("UNIT (PCS)") == "skip"
    assert vertical_header_role("UNIT PRICE (USD)") == "unit_price"
