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
