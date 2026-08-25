"""Vision LLM understandability gate — branch before legacy IQ/OCR stack."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.extraction.document_ai_provider import DocumentAiProvider
from app.services.extraction.vision_pdf import resolve_pdf_page_images
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Default floor when settings are unavailable. Prefer get_settings().
MIN_UNDERSTAND_CONFIDENCE = 0.55
HIGH_UNDERSTAND_CONFIDENCE = 0.70


def min_understand_confidence() -> float:
    from app.config import get_settings

    try:
        return float(get_settings().vision_min_understand_confidence)
    except Exception:
        return MIN_UNDERSTAND_CONFIDENCE


def high_understand_confidence() -> float:
    from app.config import get_settings

    try:
        return float(get_settings().vision_understand_high_confidence)
    except Exception:
        return HIGH_UNDERSTAND_CONFIDENCE


def understand_confidence_is_marginal(confidence: float | None) -> bool:
    """True when understood-path confidence warrants forced invoice-model DI merge."""
    if confidence is None:
        return False
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return False
    return min_understand_confidence() <= value < high_understand_confidence()


@dataclass(frozen=True)
class VisionUnderstandResult:
    can_understand: bool
    confidence: float
    reason: str
    provider: str
    page_count: int = 0
    fail_closed: bool = False


def vision_understand_audit_detail(result: VisionUnderstandResult) -> dict:
    return {
        "can_understand": result.can_understand,
        "confidence": result.confidence,
        "reason": result.reason,
        "provider": result.provider,
        "page_count": result.page_count,
        "fail_closed": result.fail_closed,
        "min_confidence": min_understand_confidence(),
    }


def _cannot(
    *,
    reason: str,
    provider: str,
    confidence: float = 0.0,
    page_count: int = 0,
    fail_closed: bool = False,
) -> VisionUnderstandResult:
    return VisionUnderstandResult(
        can_understand=False,
        confidence=confidence,
        reason=reason,
        provider=provider,
        page_count=page_count,
        fail_closed=fail_closed,
    )


async def evaluate_vision_understand(
    file_path: str | Path,
    *,
    provider: DocumentAiProvider,
    vision_page_images: list[bytes] | None = None,
) -> VisionUnderstandResult:
    """Ask vision whether it can understand the document; fail-closed to cannot."""
    from app.services.extraction.document_ai_provider import (
        provider_available,
        provider_unavailable_reason,
        probe_vision_understand,
    )

    provider_token = provider.value
    if provider not in (
        DocumentAiProvider.GEMINI_VISION,
        DocumentAiProvider.AZURE_FOUNDRY_VISION,
        DocumentAiProvider.CLAUDE_VISION,
    ):
        return _cannot(
            reason="vision_provider_not_configured",
            provider=provider_token,
            fail_closed=True,
        )
    if not provider_available(provider):
        return _cannot(
            reason=provider_unavailable_reason(provider) or "vision_unavailable",
            provider=provider_token,
            fail_closed=True,
        )

    path = Path(file_path)
    try:
        images = resolve_pdf_page_images(path, vision_page_images)
    except Exception as exc:
        logger.warning("vision_understand_raster_failed", error=str(exc))
        return _cannot(
            reason="rasterize_failed",
            provider=provider_token,
            fail_closed=True,
        )
    if not images:
        return _cannot(
            reason="no_pages",
            provider=provider_token,
            fail_closed=True,
        )

    try:
        raw = await probe_vision_understand(
            provider=provider,
            images=images,
        )
    except Exception as exc:
        logger.warning("vision_understand_probe_failed", error=str(exc))
        return _cannot(
            reason="provider_error",
            provider=provider_token,
            page_count=len(images),
            fail_closed=True,
        )

    if raw is None:
        return _cannot(
            reason="provider_empty_response",
            provider=provider_token,
            page_count=len(images),
            fail_closed=True,
        )

    claimed = bool(raw.get("can_understand"))
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(raw.get("reason") or "").strip() or (
        "vision_can_understand" if claimed else "vision_cannot_understand"
    )

    if claimed and confidence >= min_understand_confidence():
        return VisionUnderstandResult(
            can_understand=True,
            confidence=confidence,
            reason=reason,
            provider=provider_token,
            page_count=len(images),
        )

    return _cannot(
        reason=reason if not claimed else "confidence_below_floor",
        provider=provider_token,
        confidence=confidence,
        page_count=len(images),
    )
