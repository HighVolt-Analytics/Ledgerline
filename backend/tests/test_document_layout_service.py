"""Tests for Azure layout parsing helpers."""

from app.schemas.document_layout import (
    DocumentLayoutResult,
    LayoutKeyValuePair,
    LayoutParagraph,
    LayoutTable,
    LayoutTableCell,
)
from app.services.extraction.document_layout_service import parse_layout_result
from app.services.extraction.layout_field_extractor import (
    extract_document_heading_from_layout,
    extract_key_value_fields,
    infer_doc_family_hint,
)


class _Region:
    def __init__(self, page_number: int, polygon: list[float] | None = None):
        self.page_number = page_number
        self.polygon = polygon or [0, 0, 100, 0, 100, 20, 0, 20]


class _Paragraph:
    def __init__(self, content: str, page_number: int = 1):
        self.content = content
        self.bounding_regions = [_Region(page_number)]
        self.role = None


class _Cell:
    def __init__(self, content: str, row_index: int, column_index: int):
        self.content = content
        self.row_index = row_index
        self.column_index = column_index
        self.row_span = 1
        self.column_span = 1


class _Table:
    def __init__(self, cells: list[_Cell]):
        self.cells = cells
        self.bounding_regions = [_Region(1)]


class _Key:
    def __init__(self, content: str):
        self.content = content
        self.bounding_regions = [_Region(1)]


class _Value:
    def __init__(self, content: str):
        self.content = content
        self.bounding_regions = [_Region(1)]


class _KV:
    def __init__(self, key: str, value: str):
        self.key = _Key(key)
        self.value = _Value(value)


class _FakeLayoutResult:
    def __init__(self):
        self.content = "PURCHASE ORDER\nPO No: PO-44871\nVendor: Acme Supplies"
        self.pages = [object(), object()]
        self.paragraphs = [
            _Paragraph("PURCHASE ORDER", 1),
            _Paragraph("PO No:", 1),
            _Paragraph("PO-44871", 1),
            _Paragraph("Vendor:", 1),
            _Paragraph("Acme Supplies Pty Ltd", 1),
        ]
        self.tables = []
        self.key_value_pairs = [_KV("PO No", "PO-44871")]


def test_parse_layout_result_maps_paragraphs_and_kv() -> None:
    layout = parse_layout_result(_FakeLayoutResult())
    assert layout.content.startswith("PURCHASE ORDER")
    assert len(layout.paragraphs) >= 4
    assert layout.key_value_pairs[0].value == "PO-44871"


def test_extract_heading_from_layout_prefers_title_block() -> None:
    layout = parse_layout_result(_FakeLayoutResult())
    heading = extract_document_heading_from_layout(layout)
    assert heading == "PURCHASE ORDER"


def test_extract_key_value_fields_from_layout() -> None:
    layout = parse_layout_result(_FakeLayoutResult())
    fields = extract_key_value_fields(layout, layout.content)
    assert fields.get("po_reference") == "PO-44871"


def test_infer_doc_family_hint_po() -> None:
    layout = DocumentLayoutResult(
        content="PURCHASE ORDER",
        paragraphs=(LayoutParagraph("PURCHASE ORDER", 0),),
        key_value_pairs=(LayoutKeyValuePair("PO No", "PO-99"),),
    )
    assert infer_doc_family_hint(layout, "PURCHASE ORDER", layout.content) == "po"


def test_extract_line_items_from_table() -> None:
    from decimal import Decimal

    from app.services.extraction.layout_field_extractor import extract_line_items_from_tables

    layout = DocumentLayoutResult(
        tables=(
            LayoutTable(
                page_index=0,
                row_count=2,
                column_count=3,
                cells=(
                    LayoutTableCell("Description", 0, 0),
                    LayoutTableCell("Qty", 0, 1),
                    LayoutTableCell("Amount", 0, 2),
                    LayoutTableCell("Paper", 1, 0),
                    LayoutTableCell("2", 1, 1),
                    LayoutTableCell("20.00", 1, 2),
                ),
            ),
        )
    )
    items = extract_line_items_from_tables(layout)
    assert len(items) == 1
    assert items[0].description == "Paper"
    assert items[0].qty == Decimal("2")
    assert items[0].amount == Decimal("20.00")


def test_extract_line_items_from_table_with_unit_price() -> None:
    from decimal import Decimal

    from app.services.extraction.layout_field_extractor import extract_line_items_from_tables

    layout = DocumentLayoutResult(
        tables=(
            LayoutTable(
                page_index=0,
                row_count=2,
                column_count=4,
                cells=(
                    LayoutTableCell("Description", 0, 0),
                    LayoutTableCell("Qty", 0, 1),
                    LayoutTableCell("Unit Price", 0, 2),
                    LayoutTableCell("Amount", 0, 3),
                    LayoutTableCell("Catering package", 1, 0),
                    LayoutTableCell("10", 1, 1),
                    LayoutTableCell("50.00", 1, 2),
                    LayoutTableCell("500.00", 1, 3),
                ),
            ),
        )
    )
    items = extract_line_items_from_tables(layout)
    assert len(items) == 1
    assert items[0].description == "Catering package"
    assert items[0].qty == Decimal("10")
    assert items[0].unit_price == Decimal("50.00")
    assert items[0].amount == Decimal("500.00")


def test_extract_line_items_skips_tables_without_headers() -> None:
    from app.services.extraction.layout_field_extractor import extract_line_items_from_tables

    layout = DocumentLayoutResult(
        tables=(
            LayoutTable(
                page_index=0,
                row_count=2,
                column_count=4,
                cells=(
                    LayoutTableCell("Catering package", 0, 0),
                    LayoutTableCell("10", 0, 1),
                    LayoutTableCell("50.00", 0, 2),
                    LayoutTableCell("500.00", 0, 3),
                    LayoutTableCell("Paper", 1, 0),
                    LayoutTableCell("2", 1, 1),
                    LayoutTableCell("10.00", 1, 2),
                    LayoutTableCell("20.00", 1, 3),
                ),
            ),
        )
    )
    items = extract_line_items_from_tables(layout)
    assert items == []
