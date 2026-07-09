"""OCR quality signal helpers (Sprint 3 foundation)."""

from __future__ import annotations

from typing import Any


def document_handwriting_likely(payload: dict[str, Any]) -> bool:
    """Heuristic: high confidence variance across words suggests handwriting."""
    words = payload.get("ocr_words")
    if not isinstance(words, list) or len(words) < 5:
        return False
    scores: list[float] = []
    for row in words:
        if not isinstance(row, dict):
            continue
        try:
            scores.append(float(row.get("confidence", 0)))
        except (TypeError, ValueError):
            continue
    if len(scores) < 5:
        return False
    avg = sum(scores) / len(scores)
    variance = sum((s - avg) ** 2 for s in scores) / len(scores)
    return variance > 0.08 and avg < 0.85
