"""Pre-OCR layout readiness — route OCR mode without hard-rejecting."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.config import get_settings


class OcrMode(str, Enum):
    NATIVE_TEXT = "native_text"
    STANDARD_DI = "standard_di"
    VISION_FALLBACK = "vision_fallback"
    ENHANCED_SCAN = "enhanced_scan"


@dataclass(frozen=True)
class LayoutReadinessResult:
    ocr_mode: OcrMode
    allow_di_fallback: bool = False
    page_count: int = 0
    native_text_chars: int = 0
    has_native_text: bool = False
    image_area_ratio: float = 0.0
    content_density: float = 0.0
    reasons: list[str] = field(default_factory=list)
    review_hints: list[str] = field(default_factory=list)


def _pdf_layout_signals(path: Path) -> tuple[int, int, float, float]:
    """Return page_count, text_chars, image_area_ratio, content_density."""
    import fitz

    doc = fitz.open(path)
    try:
        page_count = int(doc.page_count)
        text_parts: list[str] = []
        total_page_area = 0.0
        total_image_area = 0.0
        for i in range(page_count):
            page = doc.load_page(i)
            text_parts.append(page.get_text("text") or "")
            rect = page.rect
            page_area = float(rect.width * rect.height) or 1.0
            total_page_area += page_area
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    info = doc.extract_image(xref)
                    w = float(info.get("width") or 0)
                    h = float(info.get("height") or 0)
                    # Approximate placed image area; prefer bbox if available
                    total_image_area += w * h
                except Exception:
                    continue
            # Prefer image block bboxes when present
            try:
                blocks = page.get_text("dict").get("blocks") or []
                for block in blocks:
                    if block.get("type") == 1:  # image
                        bbox = block.get("bbox") or (0, 0, 0, 0)
                        total_image_area += abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            except Exception:
                pass
        text = "\n".join(text_parts).strip()
        text_chars = len(text)
        image_ratio = min(1.0, total_image_area / total_page_area) if total_page_area else 0.0
        density = text_chars / float(max(page_count, 1))
        return page_count, text_chars, image_ratio, density
    finally:
        doc.close()


def evaluate_layout_readiness(path: str | Path) -> LayoutReadinessResult:
    """Choose OCR mode / fallback hints. Never hard-rejects."""
    file_path = Path(path)
    settings = get_settings()
    suffix = file_path.suffix.lower()
    reasons: list[str] = []
    hints: list[str] = []

    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return LayoutReadinessResult(
            ocr_mode=OcrMode.ENHANCED_SCAN,
            allow_di_fallback=False,
            page_count=1,
            reasons=["image_file"],
            review_hints=["scan_or_photo"],
        )

    if suffix == ".docx":
        return LayoutReadinessResult(
            ocr_mode=OcrMode.STANDARD_DI,
            allow_di_fallback=False,
            page_count=1,
            reasons=["docx"],
        )

    if suffix != ".pdf":
        return LayoutReadinessResult(
            ocr_mode=OcrMode.STANDARD_DI,
            reasons=[f"unknown_suffix:{suffix or 'none'}"],
        )

    try:
        page_count, text_chars, image_ratio, density = _pdf_layout_signals(file_path)
    except Exception as exc:
        return LayoutReadinessResult(
            ocr_mode=OcrMode.STANDARD_DI,
            allow_di_fallback=True,
            reasons=["layout_probe_failed", str(exc)[:80]],
            review_hints=["prefer_di"],
        )

    min_chars = int(settings.layout_native_text_min_chars)
    min_per_page = int(settings.layout_native_text_chars_per_page_min)
    mixed_ratio = float(settings.layout_mixed_pdf_image_area_ratio)

    has_native = text_chars >= min_chars and density >= min_per_page
    allow_fallback = False

    if image_ratio >= mixed_ratio and text_chars > 0:
        allow_fallback = True
        reasons.append("mixed_pdf_embedded_images")
        hints.append("native_text_may_be_incomplete")

    if has_native and text_chars < min_chars * 2 and page_count > 1:
        allow_fallback = True
        reasons.append("native_text_short_for_page_count")
        hints.append("allow_di_fallback")

    if not has_native:
        if image_ratio >= 0.15 or text_chars == 0:
            reasons.append("scan_like_or_image_only")
            return LayoutReadinessResult(
                ocr_mode=OcrMode.ENHANCED_SCAN if image_ratio >= 0.5 else OcrMode.STANDARD_DI,
                allow_di_fallback=False,
                page_count=page_count,
                native_text_chars=text_chars,
                has_native_text=False,
                image_area_ratio=image_ratio,
                content_density=density,
                reasons=reasons,
                review_hints=hints,
            )
        reasons.append("weak_native_text")
        return LayoutReadinessResult(
            ocr_mode=OcrMode.STANDARD_DI,
            allow_di_fallback=True,
            page_count=page_count,
            native_text_chars=text_chars,
            has_native_text=False,
            image_area_ratio=image_ratio,
            content_density=density,
            reasons=reasons or ["prefer_di"],
            review_hints=hints,
        )

    # Collage heuristic: many large image regions → vision fallback
    if image_ratio >= 0.7 and page_count <= 2:
        reasons.append("photo_collage_heuristic")
        return LayoutReadinessResult(
            ocr_mode=OcrMode.VISION_FALLBACK,
            allow_di_fallback=True,
            page_count=page_count,
            native_text_chars=text_chars,
            has_native_text=True,
            image_area_ratio=image_ratio,
            content_density=density,
            reasons=reasons,
            review_hints=hints + ["vision_preferred"],
        )

    reasons.append("native_text_layer")
    return LayoutReadinessResult(
        ocr_mode=OcrMode.NATIVE_TEXT,
        allow_di_fallback=allow_fallback,
        page_count=page_count,
        native_text_chars=text_chars,
        has_native_text=True,
        image_area_ratio=image_ratio,
        content_density=density,
        reasons=reasons,
        review_hints=hints or (["allow_di_fallback"] if allow_fallback else []),
    )


def layout_readiness_audit_detail(result: LayoutReadinessResult) -> dict[str, object]:
    return {
        "gate": "layout_readiness",
        "ocr_mode": result.ocr_mode.value,
        "allow_di_fallback": result.allow_di_fallback,
        "page_count": result.page_count,
        "native_text_chars": result.native_text_chars,
        "has_native_text": result.has_native_text,
        "image_area_ratio": round(result.image_area_ratio, 4),
        "content_density": round(result.content_density, 2),
        "reasons": result.reasons,
        "review_hints": result.review_hints,
    }


def native_text_ocr_artifact(path: Path) -> "OcrArtifact":
    """Build a cheap OCR artifact from the PDF text layer."""
    from app.schemas.ocr_artifact import OcrArtifact

    settings = get_settings()
    import fitz

    doc = fitz.open(path)
    try:
        parts = [(doc.load_page(i).get_text("text") or "") for i in range(doc.page_count)]
    finally:
        doc.close()
    text = "\n".join(parts).strip()
    text_length = len(text)
    sparse = text_length < settings.ocr_min_text_chars
    return OcrArtifact(
        success=bool(text_length),
        sparse=sparse,
        text=text,
        text_length=text_length,
        di_model="native_pdf_text",
        payload_json={
            "provider": "native_text",
            "text_length": text_length,
            "ocr_path_used": "native_text",
        },
    )


def native_text_looks_incomplete(ocr: "OcrArtifact", readiness: LayoutReadinessResult) -> bool:
    """Decide whether to fall back from native text to DI."""
    settings = get_settings()
    if readiness.allow_di_fallback and readiness.image_area_ratio >= float(
        settings.layout_mixed_pdf_image_area_ratio
    ):
        return True
    min_chars = int(settings.layout_native_text_min_chars)
    if ocr.text_length < min_chars:
        return True
    if readiness.page_count > 1 and ocr.text_length < min_chars * readiness.page_count * 0.5:
        return True
    if ocr.sparse:
        return True
    return False
