"""Content fingerprint for PDF text — detects duplicates across re-encoded byte streams."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from app.services.extraction.pdf_page_text_service import PdfPageText, extract_pdf_page_texts
from app.utils.hashing import compute_sha256_bytes

_WHITESPACE_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_pdf_text_blob(text: str) -> str:
    """Lowercase, strip punctuation noise, collapse whitespace."""
    cleaned = (text or "").strip().lower()
    cleaned = _NOISE_RE.sub(" ", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def compute_pdf_content_fingerprint(
    pages: list[PdfPageText],
    start_page: int,
    end_page: int,
) -> str | None:
    """SHA256 of normalized text from an inclusive page range (list indices)."""
    if not pages or start_page < 0 or end_page < start_page:
        return None

    slice_end = min(end_page, len(pages) - 1)
    if start_page >= len(pages):
        return None

    parts: list[str] = []
    for page in pages[start_page : slice_end + 1]:
        normalized = normalize_pdf_text_blob(page.text)
        if normalized:
            parts.append(normalized)

    if not parts:
        return None

    return compute_sha256_bytes("\n".join(parts).encode("utf-8"))


def compute_pdf_content_fingerprint_from_pages(pages: list[PdfPageText]) -> str | None:
    """Fingerprint the full document from pre-extracted page text."""
    if not pages:
        return None
    return compute_pdf_content_fingerprint(pages, 0, len(pages) - 1)


def compute_pdf_bytes_content_fingerprint(data: bytes) -> str | None:
    """Extract page text from PDF bytes and fingerprint the full document."""
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)

        extraction = extract_pdf_page_texts(tmp_path)
        if not extraction.pages:
            return None
        return compute_pdf_content_fingerprint_from_pages(extraction.pages)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
