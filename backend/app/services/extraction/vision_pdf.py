"""Shared PDF → page image helpers for vision LLM providers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

ImageFormat = Literal["png", "jpeg"]

DEFAULT_VISION_MAX_PAGES = 4
DEFAULT_VISION_DPI = 150
# Header identity usually lives on the first page(s); keep API payload small.
HEADER_VISION_MAX_PAGES = 2


def sniff_image_media_type(image: bytes) -> str:
    """Return image/* media type from magic bytes (png/jpeg fallback png)."""
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "image/png"


def pdf_page_count(path: Path) -> int | None:
    """Return PDF page count, or None when the file cannot be opened."""
    try:
        import fitz

        doc = fitz.open(path)
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:
        return None


def adaptive_vision_max_pages_for_count(
    page_count: int,
    *,
    default_max: int = DEFAULT_VISION_MAX_PAGES,
) -> int:
    """Smaller raster budget for short / single-page segment PDFs."""
    n = max(0, int(page_count))
    if n <= 1:
        return 1
    if n <= 3:
        return n
    return min(n, max(1, default_max))


def adaptive_vision_max_pages(
    path: Path,
    *,
    default_max: int = DEFAULT_VISION_MAX_PAGES,
) -> int:
    """Smaller raster budget for short / single-page segment PDFs."""
    count = pdf_page_count(path)
    if count is None:
        return max(1, default_max)
    return adaptive_vision_max_pages_for_count(count, default_max=default_max)


def pdf_page_images(
    path: Path,
    *,
    max_pages: int | None = None,
    dpi: int = DEFAULT_VISION_DPI,
    image_format: ImageFormat = "png",
    jpeg_quality: int = 75,
) -> list[bytes]:
    import fitz

    doc = fitz.open(path)
    try:
        images: list[bytes] = []
        fmt = (image_format or "png").strip().lower()
        if fmt not in {"png", "jpeg", "jpg"}:
            fmt = "png"
        if fmt == "jpg":
            fmt = "jpeg"
        budget = (
            max(1, int(max_pages))
            if max_pages is not None
            else adaptive_vision_max_pages_for_count(doc.page_count)
        )
        for index in range(min(doc.page_count, budget)):
            page = doc.load_page(index)
            pix = page.get_pixmap(dpi=max(36, int(dpi)), alpha=False)
            if fmt == "jpeg":
                images.append(
                    pix.tobytes(
                        "jpeg",
                        jpg_quality=max(40, min(95, int(jpeg_quality))),
                    )
                )
            else:
                images.append(pix.tobytes("png"))
        return images
    finally:
        doc.close()


def resolve_pdf_page_images(
    path: Path,
    cache: list[bytes] | None = None,
    *,
    max_pages: int | None = None,
    dpi: int = DEFAULT_VISION_DPI,
    image_format: ImageFormat = "png",
    jpeg_quality: int = 75,
) -> list[bytes]:
    """Return rasterized page images, reusing *cache* when already populated."""
    if cache is not None and len(cache) > 0:
        return cache
    images = pdf_page_images(
        path,
        max_pages=max_pages,
        dpi=dpi,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
    )
    if cache is not None:
        cache.clear()
        cache.extend(images)
        return cache
    return images


def limit_vision_images(images: list[bytes], *, max_pages: int) -> list[bytes]:
    """Return a prefix of *images* for cheaper vision API calls (cache unchanged)."""
    if max_pages <= 0 or len(images) <= max_pages:
        return images
    return images[:max_pages]

