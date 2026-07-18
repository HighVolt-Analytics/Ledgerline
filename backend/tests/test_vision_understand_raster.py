"""Vision PDF raster helpers."""

from __future__ import annotations

from app.services.extraction.vision_pdf import sniff_image_media_type


def test_sniff_image_media_type_jpeg_png() -> None:
    assert sniff_image_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff_image_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert sniff_image_media_type(b"unknown") == "image/png"
