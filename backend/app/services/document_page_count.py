"""Count billable pages in uploaded documents."""

from __future__ import annotations

import tempfile
from pathlib import Path


def count_document_pages(data: bytes, filename: str) -> int:
    """Return actual page count for credit billing (minimum 1)."""
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return _pdf_page_count(data)
    if lower.endswith((".jpg", ".jpeg", ".png", ".docx")):
        return 1
    return 1


def _pdf_page_count(data: bytes) -> int:
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)
        try:
            import fitz

            doc = fitz.open(tmp_path)
            count = max(doc.page_count, 1)
            doc.close()
            return count
        except Exception:
            try:
                import pdfplumber

                with pdfplumber.open(tmp_path) as pdf:
                    return max(len(pdf.pages), 1)
            except Exception:
                return 1
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
