"""Structured layout models from Azure prebuilt-layout analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LayoutParagraph:
    text: str
    page_index: int
    polygon: tuple[float, ...] = ()
    role: str | None = None


@dataclass(frozen=True)
class LayoutTableCell:
    text: str
    row_index: int
    column_index: int
    row_span: int = 1
    column_span: int = 1


@dataclass(frozen=True)
class LayoutTable:
    page_index: int
    row_count: int
    column_count: int
    cells: tuple[LayoutTableCell, ...] = ()


@dataclass(frozen=True)
class LayoutKeyValuePair:
    key: str
    value: str
    page_index: int = 0


@dataclass(frozen=True)
class DocumentLayoutResult:
    content: str = ""
    pages: tuple[int, ...] = ()
    paragraphs: tuple[LayoutParagraph, ...] = ()
    tables: tuple[LayoutTable, ...] = ()
    key_value_pairs: tuple[LayoutKeyValuePair, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tables(self) -> bool:
        return bool(self.tables)

    def top_paragraphs(self, *, limit: int = 8) -> list[LayoutParagraph]:
        if not self.paragraphs:
            return []
        sorted_paras = sorted(
            self.paragraphs,
            key=lambda p: (p.page_index, _paragraph_top(p.polygon)),
        )
        return list(sorted_paras[:limit])


def _paragraph_top(polygon: tuple[float, ...]) -> float:
    if len(polygon) >= 2:
        ys = [polygon[i] for i in range(1, len(polygon), 2)]
        return min(ys) if ys else 0.0
    return 0.0
