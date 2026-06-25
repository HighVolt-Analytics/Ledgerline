"""Azure Document Intelligence prebuilt-layout analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas.document_layout import (
    DocumentLayoutResult,
    LayoutKeyValuePair,
    LayoutParagraph,
    LayoutTable,
    LayoutTableCell,
)
from app.services.document_intelligence import is_di_enabled
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _polygon_tuple(polygon: Any) -> tuple[float, ...]:
    if polygon is None:
        return ()
    if isinstance(polygon, (list, tuple)):
        return tuple(float(v) for v in polygon)
    return ()


def _paragraph_from_obj(obj: Any) -> LayoutParagraph | None:
    content = (getattr(obj, "content", None) or "").strip()
    if not content:
        return None
    regions = getattr(obj, "bounding_regions", None) or []
    page_index = 0
    polygon: tuple[float, ...] = ()
    if regions:
        region = regions[0]
        page_index = int(getattr(region, "page_number", 1) or 1) - 1
        polygon = _polygon_tuple(getattr(region, "polygon", None))
    role = getattr(obj, "role", None)
    return LayoutParagraph(
        text=content,
        page_index=page_index,
        polygon=polygon,
        role=str(role) if role else None,
    )


def _table_from_obj(obj: Any) -> LayoutTable | None:
    cells_raw = getattr(obj, "cells", None) or []
    if not cells_raw:
        return None
    regions = getattr(obj, "bounding_regions", None) or []
    page_index = 0
    if regions:
        page_index = int(getattr(regions[0], "page_number", 1) or 1) - 1
    cells: list[LayoutTableCell] = []
    max_row = 0
    max_col = 0
    for cell in cells_raw:
        row = int(getattr(cell, "row_index", 0) or 0)
        col = int(getattr(cell, "column_index", 0) or 0)
        max_row = max(max_row, row)
        max_col = max(max_col, col)
        cells.append(
            LayoutTableCell(
                text=(getattr(cell, "content", None) or "").strip(),
                row_index=row,
                column_index=col,
                row_span=int(getattr(cell, "row_span", 1) or 1),
                column_span=int(getattr(cell, "column_span", 1) or 1),
            )
        )
    return LayoutTable(
        page_index=page_index,
        row_count=max_row + 1,
        column_count=max_col + 1,
        cells=tuple(cells),
    )


def _kv_from_obj(obj: Any) -> LayoutKeyValuePair | None:
    key_obj = getattr(obj, "key", None)
    val_obj = getattr(obj, "value", None)
    key = (getattr(key_obj, "content", None) or "").strip()
    value = (getattr(val_obj, "content", None) or "").strip()
    if not key and not value:
        return None
    regions = getattr(key_obj, "bounding_regions", None) or getattr(
        val_obj, "bounding_regions", None
    ) or []
    page_index = 0
    if regions:
        page_index = int(getattr(regions[0], "page_number", 1) or 1) - 1
    return LayoutKeyValuePair(key=key, value=value, page_index=page_index)


def parse_layout_result(result: Any) -> DocumentLayoutResult:
    """Map Azure DI analyze result to DocumentLayoutResult."""
    content = (getattr(result, "content", None) or "").strip()
    pages = tuple(range(len(getattr(result, "pages", None) or [])))

    paragraphs: list[LayoutParagraph] = []
    for para in getattr(result, "paragraphs", None) or []:
        mapped = _paragraph_from_obj(para)
        if mapped is not None:
            paragraphs.append(mapped)

    tables: list[LayoutTable] = []
    for table in getattr(result, "tables", None) or []:
        mapped = _table_from_obj(table)
        if mapped is not None:
            tables.append(mapped)

    kv_pairs: list[LayoutKeyValuePair] = []
    for kv in getattr(result, "key_value_pairs", None) or []:
        mapped = _kv_from_obj(kv)
        if mapped is not None:
            kv_pairs.append(mapped)

    # Fallback: synthesize paragraphs from page lines when layout has no paragraphs
    if not paragraphs:
        for index, page in enumerate(getattr(result, "pages", None) or []):
            for line in getattr(page, "lines", None) or []:
                text = (getattr(line, "content", None) or "").strip()
                if not text:
                    continue
                regions = getattr(line, "bounding_regions", None) or []
                polygon: tuple[float, ...] = ()
                if regions:
                    polygon = _polygon_tuple(getattr(regions[0], "polygon", None))
                paragraphs.append(
                    LayoutParagraph(text=text, page_index=index, polygon=polygon)
                )

    raw_snapshot: dict[str, Any] = {
        "page_count": len(pages),
        "paragraph_count": len(paragraphs),
        "table_count": len(tables),
        "kv_count": len(kv_pairs),
    }

    return DocumentLayoutResult(
        content=content,
        pages=pages,
        paragraphs=tuple(paragraphs),
        tables=tuple(tables),
        key_value_pairs=tuple(kv_pairs),
        raw=raw_snapshot,
    )


def analyze_layout_via_di(
    file_path: str | Path,
    *,
    content_type: str = "application/pdf",
) -> DocumentLayoutResult | None:
    """Analyze document with Azure prebuilt-layout. Returns None when unavailable."""
    if not is_di_enabled():
        return None

    settings = get_settings()
    path = Path(file_path)
    if not path.is_file():
        return None

    model_id = (settings.azure_di_layout_model_id or "prebuilt-layout").strip()
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:
        logger.error("di_sdk_missing", error=str(exc))
        return None

    try:
        client = DocumentIntelligenceClient(
            settings.azure_di_endpoint.rstrip("/"),
            AzureKeyCredential(settings.azure_di_key),
        )
        with path.open("rb") as document:
            poller = client.begin_analyze_document(
                model_id,
                body=document,
                content_type=content_type,
            )
        result = poller.result()
    except Exception as exc:
        logger.warning(
            "di_layout_failed",
            path=str(path),
            model_id=model_id,
            error=str(exc),
        )
        return None

    layout = parse_layout_result(result)
    logger.info(
        "di_layout_ok",
        path=str(path),
        model_id=model_id,
        paragraphs=len(layout.paragraphs),
        tables=len(layout.tables),
    )
    return layout
