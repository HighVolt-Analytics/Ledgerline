"""Tests for layout table line-item extraction."""

from decimal import Decimal

from app.schemas.document_layout import DocumentLayoutResult, LayoutTable, LayoutTableCell
from app.services.extraction.layout_field_extractor import extract_line_items_from_tables


def _table(cells: list[LayoutTableCell], *, row_count: int, column_count: int) -> LayoutTable:
    return LayoutTable(
        page_index=0,
        row_count=row_count,
        column_count=column_count,
        cells=cells,
    )


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
