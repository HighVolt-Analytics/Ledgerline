"""Embedding-based similarity between samples and catalogue document types."""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.document_type_sample_analysis import CatalogueMatchCandidate
from app.services.azure_openai_client import embed_texts, is_azure_openai_configured
from app.services.document_type_sample_types import ParsedDocumentSample


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _catalogue_text(defn: DocumentTypeDefinition) -> str:
    return " ".join(
        part
        for part in [
            defn.code,
            defn.title,
            defn.short_title,
            defn.one_line,
            defn.playbook_profile,
        ]
        if part
    ).strip()


def _sample_text(sample: ParsedDocumentSample) -> str:
    heading = (sample.parsed.document_heading or "").strip()
    hint = (sample.layout_hint or sample.parsed.raw_fields.get("layout_hint") or "").strip()
    body = (sample.parsed.document_text or "")[:500]
    return " ".join(part for part in [sample.filename, heading, hint, body] if part).strip()


def _fallback_similarity(
  sample_text: str,
  catalogue: Sequence[DocumentTypeDefinition],
) -> list[CatalogueMatchCandidate]:
    """Token overlap fallback when embeddings are unavailable."""
    sample_tokens = {token for token in sample_text.lower().split() if len(token) > 2}
    scored: list[tuple[float, DocumentTypeDefinition]] = []
    for defn in catalogue:
        if not defn.enabled:
            continue
        text = _catalogue_text(defn).lower()
        tokens = {token for token in text.split() if len(token) > 2}
        if not tokens:
            continue
        overlap = len(sample_tokens & tokens) / max(len(sample_tokens | tokens), 1)
        scored.append((overlap, defn))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [
        CatalogueMatchCandidate(
            code=defn.code,
            title=defn.title,
            similarity=round(score, 4),
            reason="Keyword overlap with catalogue entry",
        )
        for score, defn in scored[:3]
        if score > 0
    ]


def match_catalogue_for_samples(
    samples: Sequence[ParsedDocumentSample],
    catalogue: Sequence[DocumentTypeDefinition],
    *,
    limit: int = 3,
) -> list[CatalogueMatchCandidate]:
    if not catalogue or not samples:
        return []

    combined_sample = " ".join(_sample_text(sample) for sample in samples).strip()
    if not combined_sample:
        return []

    enabled = [defn for defn in catalogue if defn.enabled]
    if not enabled:
        return []

    if not is_azure_openai_configured():
        return _fallback_similarity(combined_sample, enabled)

    texts = [_catalogue_text(defn) for defn in enabled]
    vectors = embed_texts([combined_sample, *texts])
    if vectors is None or len(vectors) != len(texts) + 1:
        return _fallback_similarity(combined_sample, enabled)

    sample_vector = vectors[0]
    scored = [
        (_cosine_similarity(sample_vector, vector), defn)
        for vector, defn in zip(vectors[1:], enabled, strict=True)
    ]
    scored.sort(key=lambda row: row[0], reverse=True)
    return [
        CatalogueMatchCandidate(
            code=defn.code,
            title=defn.title,
            similarity=round(score, 4),
            reason="Embedding similarity to catalogue entry",
        )
        for score, defn in scored[:limit]
        if score > 0.05
    ]
