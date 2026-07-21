"""Vision PDF raster helpers."""

from __future__ import annotations

from pathlib import Path

from app.services.extraction.vision_pdf import (
    HEADER_VISION_MAX_PAGES,
    resolve_header_vision_images,
    sniff_image_media_type,
)


def test_sniff_image_media_type_jpeg_png() -> None:
    assert sniff_image_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff_image_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert sniff_image_media_type(b"unknown") == "image/png"


def test_header_vision_max_pages_covers_whole_upload_budget() -> None:
    assert HEADER_VISION_MAX_PAGES >= 10


def test_resolve_header_vision_images_extends_short_cache(
    tmp_path: Path, monkeypatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.extraction.vision_pdf.pdf_page_count",
        lambda _p: 5,
    )

    calls: list[int | None] = []

    def _fake_images(_path, *, max_pages=None, **_kwargs):
        calls.append(max_pages)
        n = max_pages or 1
        return [bytes([i]) for i in range(n)]

    monkeypatch.setattr(
        "app.services.extraction.vision_pdf.pdf_page_images",
        _fake_images,
    )

    cache = [b"\x00", b"\x01"]  # understand-gate only kept 2 pages
    images = resolve_header_vision_images(pdf, cache, max_pages=5)
    assert len(images) == 5
    assert len(cache) == 5
    assert calls == [5]
