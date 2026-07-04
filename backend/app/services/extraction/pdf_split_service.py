"""Split a PDF into byte ranges (one stored file per logical document)."""

from __future__ import annotations

from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_pdf_page_range_bytes(source: Path, start_page: int, end_page: int) -> bytes:
    """Extract inclusive page range into a new PDF byte stream."""
    import fitz

    if start_page < 0 or end_page < start_page:
        raise ValueError(f"invalid page range {start_page}..{end_page}")

    doc = fitz.open(source)
    try:
        if end_page >= doc.page_count:
            raise ValueError(f"end_page {end_page} out of range (pages={doc.page_count})")
        out = fitz.open()
        try:
            out.insert_pdf(doc, from_page=start_page, to_page=end_page)
            payload = out.tobytes()
        finally:
            out.close()
    finally:
        doc.close()

    logger.info(
        "pdf_page_range_extracted",
        source=str(source),
        start_page=start_page,
        end_page=end_page,
        bytes=len(payload),
    )
    return payload


def segment_upload_filename(original: str, segment_index: int, segment_count: int) -> str:
    """Stable stored filename for a segment slice."""
    stem = Path(original).stem or "document"
    suffix = Path(original).suffix or ".pdf"
    if segment_count <= 1:
        return f"{stem}{suffix}"
    return f"{stem}__part{segment_index + 1}of{segment_count}{suffix}"
