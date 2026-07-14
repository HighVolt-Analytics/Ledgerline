"""Shared PDF → page image helpers for vision LLM providers."""

from __future__ import annotations

from pathlib import Path


def pdf_page_images(path: Path, *, max_pages: int = 8) -> list[bytes]:
    import fitz

    doc = fitz.open(path)
    try:
        images: list[bytes] = []
        for index in range(min(doc.page_count, max_pages)):
            page = doc.load_page(index)
            pix = page.get_pixmap(dpi=150)
            images.append(pix.tobytes("png"))
        return images
    finally:
        doc.close()


def resolve_pdf_page_images(
    path: Path,
    cache: list[bytes] | None = None,
    *,
    max_pages: int = 8,
) -> list[bytes]:
    """Return rasterized page PNGs, reusing *cache* when already populated."""
    if cache is not None and len(cache) > 0:
        return cache
    images = pdf_page_images(path, max_pages=max_pages)
    if cache is not None:
        cache.clear()
        cache.extend(images)
        return cache
    return images
