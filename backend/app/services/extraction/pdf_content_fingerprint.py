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


def pdf_text_token_set(text: str) -> frozenset[str]:
    """Word bag from the same normalization used for content fingerprints."""
    normalized = normalize_pdf_text_blob(text)
    if not normalized:
        return frozenset()
    return frozenset(normalized.split())


def jaccard_token_similarity(left: str, right: str) -> float:
    """Jaccard similarity over normalized word bags (0–1)."""
    a = pdf_text_token_set(left)
    b = pdf_text_token_set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def boost_confidence_with_content_similarity(
    base_confidence: float,
    left_text: str | None,
    right_text: str | None,
    *,
    threshold: float | None = None,
    boost: float = 0.15,
) -> tuple[float, float | None]:
    """If similarity >= threshold, raise confidence (capped at 1.0). Returns (confidence, similarity)."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.content_similarity_check_enabled:
        return base_confidence, None
    if not (left_text or "").strip() or not (right_text or "").strip():
        return base_confidence, None
    if threshold is None:
        threshold = float(settings.content_similarity_threshold)
    sim = jaccard_token_similarity(left_text or "", right_text or "")
    if sim >= threshold:
        return min(1.0, round(base_confidence + boost, 4)), sim
    return base_confidence, sim


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
