"""Pre-OCR visual fitness checks — cheap raster heuristics before DI/OCR spend."""

from __future__ import annotations

import io
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.config import get_settings
from app.services.extraction.vision_pdf import resolve_pdf_page_images

SignalLevel = Literal["pass", "warn", "severe"]


@dataclass(frozen=True)
class ImageQualitySignal:
    name: str
    level: SignalLevel
    metric: float | None = None
    threshold: float | None = None
    page_index: int = 0
    detail: str | None = None


@dataclass(frozen=True)
class ImageQualityResult:
    passed: bool
    severity: SignalLevel  # worst level across signals
    signals: list[ImageQualitySignal] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    page_count_checked: int = 0


def _level_rank(level: SignalLevel) -> int:
    return {"pass": 0, "warn": 1, "severe": 2}[level]


def _worst_level(signals: list[ImageQualitySignal]) -> SignalLevel:
    if not signals:
        return "pass"
    return max((s.level for s in signals), key=_level_rank)


def _grayscale_pixels(png_bytes: bytes) -> tuple[list[int], int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as img:
        gray = img.convert("L")
        width, height = gray.size
        # Downsample for speed on large pages
        max_edge = 800
        if max(width, height) > max_edge:
            scale = max_edge / float(max(width, height))
            gray = gray.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.BILINEAR,
            )
            width, height = gray.size
        return list(gray.getdata()), width, height


def _contrast_std(pixels: list[int]) -> float:
    if len(pixels) < 2:
        return 0.0
    return float(statistics.pstdev(pixels))


def _content_fill_ratio(pixels: list[int], width: int, height: int) -> float:
    if not pixels or width < 1 or height < 1:
        return 0.0
    mean = statistics.fmean(pixels)
    # Ink-ish pixels deviate from page mean
    ink = sum(1 for p in pixels if abs(p - mean) > 18)
    return ink / float(len(pixels))


def _estimate_skew_degrees(pixels: list[int], width: int, height: int) -> float:
    """Projection-profile skew estimate (degrees). Conservative / noisy — warn-first."""
    if width < 16 or height < 16:
        return 0.0
    # Sample a few candidate angles
    best_var = -1.0
    best_angle = 0.0
    for angle in (-12.0, -6.0, 0.0, 6.0, 12.0, -20.0, 20.0):
        rad = math.radians(angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        bins = [0] * height
        step = max(1, width // 80)
        for y in range(0, height, step):
            row = 0
            for x in range(0, width, step):
                # Approximate rotate around center for projection onto y
                cx, cy = x - width / 2.0, y - height / 2.0
                ny = int(cx * sin_a + cy * cos_a + height / 2.0)
                if 0 <= ny < height:
                    px = pixels[y * width + x]
                    if px < 200:
                        row += 1
            if 0 <= y < height:
                bins[y] += row
        var = statistics.pvariance(bins) if len(bins) > 1 else 0.0
        if var > best_var:
            best_var = var
            best_angle = abs(angle)
    # If 0° is best, skew ~0; else report the winning tilt magnitude as heuristic
    if best_angle == 0.0:
        return 0.0
    # Prefer reporting small non-zero only when 0 is not best
    zero_bins = [0] * height
    step = max(1, width // 80)
    for y in range(0, height, step):
        for x in range(0, width, step):
            if pixels[y * width + x] < 200:
                zero_bins[y] += 1
    zero_var = statistics.pvariance(zero_bins) if len(zero_bins) > 1 else 0.0
    if best_var <= zero_var * 1.05:
        return 0.0
    return float(best_angle)


def _pdf_page_sizes_inches(path: Path, max_pages: int) -> list[tuple[float, float]]:
    try:
        import fitz

        doc = fitz.open(path)
        try:
            sizes: list[tuple[float, float]] = []
            for i in range(min(doc.page_count, max_pages)):
                page = doc.load_page(i)
                rect = page.rect
                # PDF points → inches (72 pt/inch)
                sizes.append((float(rect.width) / 72.0, float(rect.height) / 72.0))
            return sizes
        finally:
            doc.close()
    except Exception:
        return []


def _orientation_suspect(width: int, height: int, *, page_w_in: float | None, page_h_in: float | None) -> bool:
    if width < 1 or height < 1:
        return False
    # Landscape pixel image for a portrait PDF page (or vice versa) is suspicious
    if page_w_in and page_h_in and page_w_in > 0 and page_h_in > 0:
        page_landscape = page_w_in > page_h_in
        img_landscape = width > height
        return page_landscape != img_landscape
    # Phone photos: very wide landscape of a typical A4-ish doc is mild suspect only
    return width > height * 1.35


def _analyze_page(
    png_bytes: bytes,
    *,
    page_index: int,
    page_w_in: float | None,
    page_h_in: float | None,
) -> list[ImageQualitySignal]:
    settings = get_settings()
    signals: list[ImageQualitySignal] = []
    try:
        pixels, width, height = _grayscale_pixels(png_bytes)
    except Exception as exc:
        return [
            ImageQualitySignal(
                name="raster_open_failed",
                level="severe",
                page_index=page_index,
                detail=str(exc)[:120],
            )
        ]

    min_dim = int(settings.image_quality_min_dimension_px)
    if min(width, height) < min_dim:
        signals.append(
            ImageQualitySignal(
                name="tiny_dimensions",
                level="severe",
                metric=float(min(width, height)),
                threshold=float(min_dim),
                page_index=page_index,
            )
        )

    if page_w_in and page_h_in and page_w_in > 0 and page_h_in > 0:
        dpi_x = width / page_w_in
        dpi_y = height / page_h_in
        approx_dpi = min(dpi_x, dpi_y)
        min_dpi = float(settings.image_quality_min_approx_dpi)
        if approx_dpi < min_dpi:
            # Extreme low DPI → severe; moderate → warn
            level: SignalLevel = "severe" if approx_dpi < min_dpi * 0.55 else "warn"
            signals.append(
                ImageQualitySignal(
                    name="low_approx_dpi",
                    level=level,
                    metric=approx_dpi,
                    threshold=min_dpi,
                    page_index=page_index,
                )
            )

    contrast = _contrast_std(pixels)
    blank_var_max = float(settings.image_quality_blank_variance_max)
    contrast_warn = float(settings.image_quality_min_contrast_std)
    contrast_severe = float(settings.image_quality_contrast_severe_std)

    if contrast <= blank_var_max:
        signals.append(
            ImageQualitySignal(
                name="blank_page",
                level="severe",
                metric=contrast,
                threshold=blank_var_max,
                page_index=page_index,
            )
        )
    elif contrast < contrast_severe:
        signals.append(
            ImageQualitySignal(
                name="low_contrast",
                level="severe",
                metric=contrast,
                threshold=contrast_severe,
                page_index=page_index,
            )
        )
    elif contrast < contrast_warn:
        # Mild low contrast — warn only (noisy on real traffic)
        signals.append(
            ImageQualitySignal(
                name="low_contrast",
                level="warn",
                metric=contrast,
                threshold=contrast_warn,
                page_index=page_index,
            )
        )

    fill = _content_fill_ratio(pixels, width, height)
    fill_min = float(settings.image_quality_content_fill_min)
    if fill < fill_min:
        level = "severe" if fill < fill_min * 0.35 else "warn"
        signals.append(
            ImageQualitySignal(
                name="crop_bounds",
                level=level,
                metric=fill,
                threshold=fill_min,
                page_index=page_index,
            )
        )

    skew = _estimate_skew_degrees(pixels, width, height)
    skew_warn = float(settings.image_quality_skew_warn_degrees)
    skew_severe = float(settings.image_quality_skew_severe_degrees)
    if skew >= skew_severe:
        signals.append(
            ImageQualitySignal(
                name="simple_skew",
                level="severe",
                metric=skew,
                threshold=skew_severe,
                page_index=page_index,
            )
        )
    elif skew >= skew_warn:
        signals.append(
            ImageQualitySignal(
                name="simple_skew",
                level="warn",
                metric=skew,
                threshold=skew_warn,
                page_index=page_index,
            )
        )

    if _orientation_suspect(width, height, page_w_in=page_w_in, page_h_in=page_h_in):
        # Orientation is noisy — warn by default (never severe in v1)
        signals.append(
            ImageQualitySignal(
                name="orientation_suspect",
                level="warn",
                metric=float(width) / float(height) if height else None,
                page_index=page_index,
            )
        )

    return signals


def evaluate_pre_ocr_image_quality(
    path: str | Path,
    *,
    vision_page_images: list[bytes] | None = None,
) -> ImageQualityResult:
    """Visual fitness before OCR. Severe → reject; warn → continue with audit."""
    file_path = Path(path)
    settings = get_settings()
    max_pages = int(settings.image_quality_max_pages_check)
    suffix = file_path.suffix.lower()
    signals: list[ImageQualitySignal] = []

    page_sizes: list[tuple[float, float]] = []
    try:
        if suffix == ".pdf":
            page_sizes = _pdf_page_sizes_inches(file_path, max_pages)
            images = resolve_pdf_page_images(file_path, vision_page_images, max_pages=max_pages)
        elif suffix in {".jpg", ".jpeg", ".png"}:
            from PIL import Image

            with Image.open(file_path) as img:
                w, h = img.size
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                png = buf.getvalue()
            if vision_page_images is not None:
                vision_page_images.clear()
                vision_page_images.append(png)
            images = [png]
            # Approx inches at 150 dpi assumption for native images
            page_sizes = [(w / 150.0, h / 150.0)]
        elif suffix == ".docx":
            # No raster probe in v1 — pass through
            return ImageQualityResult(passed=True, severity="pass", page_count_checked=0)
        else:
            return ImageQualityResult(
                passed=False,
                severity="severe",
                signals=[
                    ImageQualitySignal(
                        name="raster_open_failed",
                        level="severe",
                        detail=f"unsupported_suffix:{suffix or 'none'}",
                    )
                ],
                review_reasons=["IMAGE_QUALITY_LOW"],
            )
    except Exception as exc:
        return ImageQualityResult(
            passed=False,
            severity="severe",
            signals=[
                ImageQualitySignal(
                    name="raster_open_failed",
                    level="severe",
                    detail=str(exc)[:160],
                )
            ],
            review_reasons=["IMAGE_QUALITY_LOW"],
        )

    if not images:
        return ImageQualityResult(
            passed=False,
            severity="severe",
            signals=[
                ImageQualitySignal(name="raster_open_failed", level="severe", detail="no_pages")
            ],
            review_reasons=["IMAGE_QUALITY_LOW"],
        )

    for idx, png in enumerate(images[:max_pages]):
        w_in = page_sizes[idx][0] if idx < len(page_sizes) else None
        h_in = page_sizes[idx][1] if idx < len(page_sizes) else None
        signals.extend(
            _analyze_page(png, page_index=idx, page_w_in=w_in, page_h_in=h_in)
        )

    severity = _worst_level(signals)
    reasons: list[str] = []
    if any(s.level != "pass" for s in signals):
        reasons.append("IMAGE_QUALITY_LOW")
    # Deduplicate reasons
    seen: set[str] = set()
    reasons = [r for r in reasons if not (r in seen or seen.add(r))]

    return ImageQualityResult(
        passed=severity != "severe",
        severity=severity,
        signals=signals,
        review_reasons=reasons,
        page_count_checked=min(len(images), max_pages),
    )


def image_quality_pre_ocr_audit_detail(result: ImageQualityResult) -> dict[str, object]:
    return {
        "gate": "image_quality",
        "phase": "pre_ocr",
        "passed": result.passed,
        "severity": result.severity,
        "review_reasons": result.review_reasons,
        "page_count_checked": result.page_count_checked,
        "signals": [
            {
                "name": s.name,
                "level": s.level,
                "metric": s.metric,
                "threshold": s.threshold,
                "page_index": s.page_index,
                "detail": s.detail,
            }
            for s in result.signals
        ],
        "resubmit_hint": "Please resend a flat, well-lit scan or PDF — avoid blank or tiny images.",
    }
