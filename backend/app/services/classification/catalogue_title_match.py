"""Match vision document titles to Rule Book catalogue rows (no hardcoded DT names).

Vision supplies a printed title; we score that string against each enabled catalogue
row's shortTitle / title (and positive recognition prompt). A clear winner becomes
the DT. Description/summary is used later by the LLM catalogue fallback when the
title does not uniquely match.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.classification_learning_service import (
    normalize_heading_for_learning,
)

_TITLE_MATCH_THRESHOLD = 0.92
_TITLE_AMBIGUITY_MARGIN = 0.05
_MIN_TITLE_CHARS = 4

_SUFFIX_NOISE = re.compile(
    r"\b(?:form|document|sheet|voucher|note|request|requisition)\b$",
    re.I,
)


def normalize_vision_title(heading: str | None) -> str:
    return normalize_heading_for_learning(heading)


def _core_title(normalized: str) -> str:
    """Drop trailing generic words so 'Advance Requisition Form' ≈ 'Advance Requisition'."""
    token = (normalized or "").strip()
    if not token:
        return ""
    # Only strip one trailing noise word when the remainder stays meaningful.
    stripped = _SUFFIX_NOISE.sub("", token).strip()
    if len(stripped) >= _MIN_TITLE_CHARS:
        return stripped
    return token


def _token_set(normalized: str) -> set[str]:
    return {part for part in normalized.split() if len(part) >= 2}


def score_definition_for_vision_title(
    heading: str,
    definition: DocumentTypeDefinition,
) -> float:
    """Score how well a vision title matches one catalogue row (0..1)."""
    if not getattr(definition, "enabled", True):
        return 0.0
    needle = normalize_vision_title(heading)
    if len(needle) < _MIN_TITLE_CHARS:
        return 0.0

    short = normalize_vision_title(getattr(definition, "short_title", None) or "")
    title = normalize_vision_title(getattr(definition, "title", None) or "")
    best = 0.0

    for label in (short, title):
        if not label or len(label) < _MIN_TITLE_CHARS:
            continue
        if needle == label:
            best = max(best, 1.0)
            continue
        needle_core = _core_title(needle)
        label_core = _core_title(label)
        if needle_core and label_core and needle_core == label_core:
            best = max(best, 0.98)
            continue
        if label in needle or needle in label:
            best = max(best, 0.95)
            continue
        if label_core and (label_core in needle or needle_core in label_core):
            best = max(best, 0.94)

    # Multi-word overlap against short title (catalogue identity).
    if short:
        left = _token_set(needle)
        right = _token_set(short)
        if len(right) >= 2 and left:
            overlap = len(left & right) / float(len(right))
            if overlap >= 1.0:
                best = max(best, 0.96)
            elif overlap >= 0.8:
                best = max(best, 0.93)

    # Prompt-mode rows: vision title phrase appears positively in the recognition prompt.
    prompt = (getattr(definition, "llm_prompt", None) or "").strip().lower()
    if prompt and len(needle) >= _MIN_TITLE_CHARS and needle in prompt:
        if not re.search(
            rf"(?i)(?:do\s+not\s+classify|never\s+classify|exclude)[^.!?\n]{{0,80}}{re.escape(needle)}",
            prompt,
        ):
            best = max(best, 0.93)
    needle_core = _core_title(needle)
    if (
        prompt
        and needle_core
        and len(needle_core) >= _MIN_TITLE_CHARS
        and needle_core != needle
        and needle_core in prompt
    ):
        if not re.search(
            rf"(?i)(?:do\s+not\s+classify|never\s+classify|exclude)[^.!?\n]{{0,80}}{re.escape(needle_core)}",
            prompt,
        ):
            best = max(best, 0.92)

    return best


def match_catalogue_dt_by_vision_title(
    *,
    document_heading: str,
    document_types: Sequence[DocumentTypeDefinition],
) -> tuple[DocumentTypeDefinition, float, str | None, float | None] | None:
    """Return (winner, score, runner_up_code, runner_up_score) or None.

    Requires a clear margin so two similarly titled catalogue rows do not force a guess.
    """
    enabled = [dt for dt in document_types if getattr(dt, "enabled", True)]
    if not enabled:
        return None
    if len(normalize_vision_title(document_heading)) < _MIN_TITLE_CHARS:
        return None

    scored: list[tuple[DocumentTypeDefinition, float]] = []
    for definition in enabled:
        score = score_definition_for_vision_title(document_heading, definition)
        if score >= _TITLE_MATCH_THRESHOLD:
            scored.append((definition, score))
    if not scored:
        return None

    scored.sort(
        key=lambda item: (
            item[1],
            -int(getattr(item[0].classifier, "priority", 100) or 100),
        ),
        reverse=True,
    )
    best_def, best_score = scored[0]
    runner_up_code: str | None = None
    runner_up_score: float | None = None
    if len(scored) > 1:
        runner_up_code = (scored[1][0].code or "").strip().upper() or None
        runner_up_score = scored[1][1]
        if (best_score - float(runner_up_score)) < _TITLE_AMBIGUITY_MARGIN:
            return None
    return best_def, best_score, runner_up_code, runner_up_score
