"""Tests for layout table line-item extraction."""

from decimal import Decimal

from app.schemas.document_layout import DocumentLayoutResult, LayoutTable, LayoutTableCell
from app.services.extraction.layout_field_extractor import (
    extract_line_items_from_tables,
    parse_line_items_from_table_grid,
)


def _table(cells: list[LayoutTableCell], *, row_count: int, column_count: int) -> LayoutTable:
    return LayoutTable(
        page_index=0,
        row_count=row_count,
        column_count=column_count,
        cells=cells,
    )


def _cell(row: int, col: int, text: str) -> LayoutTableCell:
    return LayoutTableCell(row_index=row, column_index=col, text=text, row_span=1, column_span=1)


def test_extract_qty_only_rows_with_merged_plt_cells() -> None:
    cells = [
        LayoutTableCell(row_index=0, column_index=0, text="PART", row_span=1, column_span=1),
        LayoutTableCell(row_index=0, column_index=1, text="MODEL", row_span=1, column_span=1),
        LayoutTableCell(row_index=0, column_index=2, text="QTY", row_span=1, column_span=1),
        LayoutTableCell(row_index=0, column_index=3, text="PLT NO", row_span=1, column_span=1),
        LayoutTableCell(row_index=0, column_index=4, text="PLT DIMENSION", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=0, text="CPU CHIPS 14 Gen I3 14100", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=1, text="I3-14100", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=2, text="150", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=3, text="1", row_span=4, column_span=1),
        LayoutTableCell(row_index=1, column_index=4, text="81 X 61 X 97", row_span=4, column_span=1),
        LayoutTableCell(row_index=2, column_index=0, text="CPU CHIPS 14 Gen I5 14400", row_span=1, column_span=1),
        LayoutTableCell(row_index=2, column_index=1, text="I5-14400", row_span=1, column_span=1),
        LayoutTableCell(row_index=2, column_index=2, text="70", row_span=1, column_span=1),
        LayoutTableCell(row_index=3, column_index=0, text="CPU CHIPS 14 Gen I5 14500", row_span=1, column_span=1),
        LayoutTableCell(row_index=3, column_index=1, text="I5-14500", row_span=1, column_span=1),
        LayoutTableCell(row_index=3, column_index=2, text="130", row_span=1, column_span=1),
        LayoutTableCell(row_index=4, column_index=0, text="CPU CHIPS 14 Gen I7 14700", row_span=1, column_span=1),
        LayoutTableCell(row_index=4, column_index=1, text="I7-14700", row_span=1, column_span=1),
        LayoutTableCell(row_index=4, column_index=2, text="200", row_span=1, column_span=1),
        LayoutTableCell(row_index=5, column_index=0, text="CPU CHIPS 14 Gen I9 14900", row_span=1, column_span=1),
        LayoutTableCell(row_index=5, column_index=1, text="I9-14900", row_span=1, column_span=1),
        LayoutTableCell(row_index=5, column_index=2, text="10", row_span=1, column_span=1),
        LayoutTableCell(row_index=6, column_index=0, text="TOTALS", row_span=1, column_span=1),
        LayoutTableCell(row_index=6, column_index=2, text="560", row_span=1, column_span=1),
    ]
    layout = DocumentLayoutResult(tables=[_table(cells, row_count=7, column_count=5)])
    items = extract_line_items_from_tables(layout)
    assert len(items) == 5
    assert items[0].qty == Decimal("150")
    assert "CPU CHIPS 14 Gen I3 14100" in items[0].description
    assert "1" in items[0].description
    assert "81 X 61 X 97" in items[0].description
    assert items[4].qty == Decimal("10")
    assert all(item.amount is None and item.unit_price is None for item in items)


def test_extract_headerless_money_table_rows() -> None:
    cells = [
        LayoutTableCell(row_index=0, column_index=0, text="Widget A", row_span=1, column_span=1),
        LayoutTableCell(row_index=0, column_index=1, text="2", row_span=1, column_span=1),
        LayoutTableCell(row_index=0, column_index=2, text="10.00", row_span=1, column_span=1),
        LayoutTableCell(row_index=0, column_index=3, text="20.00", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=0, text="Widget B", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=1, text="1", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=2, text="5.00", row_span=1, column_span=1),
        LayoutTableCell(row_index=1, column_index=3, text="5.00", row_span=1, column_span=1),
    ]
    layout = DocumentLayoutResult(tables=[_table(cells, row_count=2, column_count=4)])
    items = extract_line_items_from_tables(layout)
    assert len(items) == 2
    assert items[0].description == "Widget A"
    assert items[0].qty == Decimal("2")
    assert items[0].unit_price == Decimal("10.00")
    assert items[0].amount == Decimal("20.00")


def test_extract_po_grid_name_unit_price_amount() -> None:
    """Spectra-style PO: Name + UNIT PRICE/AMOUNT must bind (not S/N / UNIT PCS)."""
    rows = [
        ["S/N", "Name", "Type", "UNIT (PCS)", "QTY", "UNIT PRICE (USD)", "AMOUNT (USD)"],
        ["1", "14 Gen i3 14100", "Tray", "PCS", "150", "115.00", "17,250.00"],
        ["2", "Core Ultra 5 225", "Tray", "PCS", "330", "137.00", "45,210.00"],
        ["3", "Core Ultra 7 265", "Tray", "PCS", "10", "315.00", "3,150.00"],
    ]
    items = parse_line_items_from_table_grid(rows)
    assert len(items) == 3
    assert "14 Gen i3 14100" in (items[0].description or "")
    assert items[0].qty == Decimal("150")
    assert items[0].unit_price == Decimal("115.00")
    assert items[0].amount == Decimal("17250.00")
    assert "Core Ultra 5 225" in (items[1].description or "")
    assert items[1].qty == Decimal("330")
    assert items[1].unit_price == Decimal("137.00")
    assert items[2].unit_price == Decimal("315.00")


def test_extract_gst_column_from_printed_cells_only() -> None:
    rows = [
        ["DESCRIPTION", "QTY", "UNIT PRICE", "GST", "AMOUNT"],
        ["R&D Tax Incentive Consulting - May 2026", "12", "450.00", "540.00", "5940.00"],
        ["Advisory Workshop - Compliance Review", "1", "2200.00", "220.00", "2420.00"],
    ]
    items = parse_line_items_from_table_grid(rows)
    assert len(items) == 2
    assert items[0].description == "R&D Tax Incentive Consulting - May 2026"
    assert items[0].qty == Decimal("12")
    assert items[0].unit_price == Decimal("450.00")
    assert items[0].tax_amount == Decimal("540.00")
    assert items[0].amount == Decimal("5940.00")
    assert items[1].unit_price == Decimal("2200.00")
    assert items[1].tax_amount == Decimal("220.00")
    assert items[1].amount == Decimal("2420.00")


def test_extract_skips_cgst_sgst_totals_table() -> None:
    """Sub Total / CGST @ 9% / Grand Total must never become product lines (amount≠rate)."""
    rows = [
        ["Sub Total", ":selected: 2,05,600.00"],
        ["CGST @ 9%", ":selected: 18,504.00"],
        ["SGST @ 9%", ":selected: 18,504.00"],
        ["Grand Total", "12,42,608.00"],
    ]
    assert parse_line_items_from_table_grid(rows) == []


def test_extract_grn_prefers_accepted_qty() -> None:
    rows = [
        ["S.No", "Item Description", "PO Qty", "Recd Qty", "Accepted", "Rejected", "Remarks"],
        ["1", "Steel Rods 12mm TMT", "500 Kg", "500 Kg", "500 Kg", "0", "Full batch accepted"],
        ["2", 'Hydraulic Hose 3/4"', "150 Nos", "150 Nos", "147 Nos", "3 Nos", "thread damage"],
        ["3", "Heavy Duty Gloves", "200 Pair", "195 Pair", "195 Pair", "0", "short delivery"],
    ]
    items = parse_line_items_from_table_grid(rows)
    assert len(items) == 3
    assert items[0].qty == Decimal("500")
    assert items[1].qty == Decimal("147")
    assert items[2].qty == Decimal("195")
    assert all(item.unit_price is None and item.amount is None for item in items)


def test_extract_grn_accepted_rank_even_when_leftmost() -> None:
    """Qty preference is rank-based, not last matching column."""
    rows = [
        ["Item Description", "Accepted", "PO Qty", "Recd Qty"],
        ["Widget Alpha", "40", "50", "45"],
        ["Widget Beta", "9", "10", "10"],
    ]
    items = parse_line_items_from_table_grid(rows)
    assert len(items) == 2
    assert items[0].qty == Decimal("40")
    assert items[1].qty == Decimal("9")


def test_extract_skips_round_off_and_taxable_footer_table() -> None:
    rows = [
        ["Taxable Amount", "10,000.00"],
        ["CGST @ 9%", "900.00"],
        ["Round Off", "0.05"],
        ["Freight Total", "50.00"],
        ["Grand Total", "10,950.05"],
    ]
    assert parse_line_items_from_table_grid(rows) == []


def test_extract_product_table_ignores_adjacent_round_off_footer() -> None:
    product = [
        _cell(0, 0, "Description"),
        _cell(0, 1, "Qty"),
        _cell(0, 2, "Unit Price"),
        _cell(0, 3, "Amount"),
        _cell(1, 0, "Consulting day rate"),
        _cell(1, 1, "2"),
        _cell(1, 2, "500.00"),
        _cell(1, 3, "1000.00"),
    ]
    footer = [
        _cell(0, 0, "Taxable Value"),
        _cell(0, 1, "1000.00"),
        _cell(1, 0, "CESS"),
        _cell(1, 1, "10.00"),
        _cell(2, 0, "Round Off"),
        _cell(2, 1, "0.00"),
    ]
    layout = DocumentLayoutResult(
        tables=[
            _table(product, row_count=2, column_count=4),
            _table(footer, row_count=3, column_count=2),
        ]
    )
    items = extract_line_items_from_tables(layout)
    assert len(items) == 1
    assert items[0].description == "Consulting day rate"
    assert items[0].amount == Decimal("1000.00")


def test_extract_skips_kv_metadata_table() -> None:
    cells = [
        _cell(0, 0, "Invoice Date"),
        _cell(0, 1, "2026-05-11"),
        _cell(1, 0, "Due Date"),
        _cell(1, 1, "2026-06-10"),
        _cell(2, 0, "Currency"),
        _cell(2, 1, "AUD"),
        _cell(3, 0, "Cost Centre"),
        _cell(3, 1, "CC-100"),
    ]
    layout = DocumentLayoutResult(tables=[_table(cells, row_count=4, column_count=2)])
    assert extract_line_items_from_tables(layout) == []


def test_extract_qty_amount_without_unit_price_cell_stays_null() -> None:
    rows = [
        ["Description", "Qty", "Amount"],
        ["Steel Mounting Brackets - Type B", "500", "60000.00"],
    ]
    items = parse_line_items_from_table_grid(rows)
    assert len(items) == 1
    assert items[0].qty == Decimal("500")
    assert items[0].amount == Decimal("60000.00")
    assert items[0].unit_price is None


def test_extract_keeps_printed_values_when_arithmetic_mismatches() -> None:
    rows = [
        ["Description", "Qty", "Unit Price", "Amount"],
        ["Odd line", "2", "10.00", "25.00"],
    ]
    items = parse_line_items_from_table_grid(rows)
    assert len(items) == 1
    assert items[0].qty == Decimal("2")
    assert items[0].unit_price == Decimal("10.00")
    assert items[0].amount == Decimal("25.00")


def test_extract_product_table_with_adjacent_kv_table() -> None:
    kv = [
        _cell(0, 0, "Invoice Date"),
        _cell(0, 1, "2026-05-11"),
        _cell(1, 0, "Currency"),
        _cell(1, 1, "AUD"),
    ]
    product = [
        _cell(0, 0, "DESCRIPTION"),
        _cell(0, 1, "QTY"),
        _cell(0, 2, "UNIT PRICE"),
        _cell(0, 3, "GST"),
        _cell(0, 4, "AMOUNT"),
        _cell(1, 0, "Advisory Workshop"),
        _cell(1, 1, "1"),
        _cell(1, 2, "2200.00"),
        _cell(1, 3, "220.00"),
        _cell(1, 4, "2420.00"),
    ]
    layout = DocumentLayoutResult(
        tables=[
            _table(kv, row_count=2, column_count=2),
            _table(product, row_count=2, column_count=5),
        ]
    )
    items = extract_line_items_from_tables(layout)
    assert len(items) == 1
    assert items[0].description == "Advisory Workshop"
    assert items[0].unit_price == Decimal("2200.00")
    assert items[0].tax_amount == Decimal("220.00")
    assert items[0].amount == Decimal("2420.00")
