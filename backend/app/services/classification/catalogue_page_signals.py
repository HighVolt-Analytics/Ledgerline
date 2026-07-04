"""Compile tenant document-type catalogue into per-page matchers for ingest splitting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas.document_type import DocumentTypeDefinition
from app.services.extraction.document_heading_utils import infer_page_document_kind, is_continuation_page

_TEXT_FIELDS = frozenset({"document_text", "document_heading", "attachment_name"})
_MIN_PHRASE_LEN = 4


@dataclass(frozen=True)
class CataloguePageMatcher:
    dt_code: str
    phrases: tuple[str, ...]
    text_contains: tuple[str, ...]


def _walk_classifier_contains(node: dict[str, Any], out: list[str]) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "condition":
        field = str(node.get("field") or "")
        op = str(node.get("operator") or "")
        value = str(node.get("value") or "").strip().lower()
        if field in _TEXT_FIELDS and op in {"contains", "starts_with", "equals"} and len(value) >= 3:
            out.append(value)
        return
    if node.get("type") == "group":
        for child in node.get("children") or []:
            if isinstance(child, dict):
                _walk_classifier_contains(child, out)


def build_catalogue_page_matchers(
    document_types: list[DocumentTypeDefinition] | tuple[DocumentTypeDefinition, ...],
) -> list[CataloguePageMatcher]:
    matchers: list[CataloguePageMatcher] = []
    for defn in document_types:
        if not defn.enabled:
            continue
        phrases: list[str] = []
        for raw in (defn.short_title, defn.title, defn.one_line):
            token = (raw or "").strip().lower()
            if len(token) >= _MIN_PHRASE_LEN:
                phrases.append(token)
        for raw in defn.extraction or []:
            token = str(raw or "").strip().lower()
            if len(token) >= _MIN_PHRASE_LEN:
                phrases.append(token)

        contains: list[str] = []
        classifier = defn.classifier
        if classifier and classifier.enabled:
            _walk_classifier_contains(classifier.root, contains)

        deduped_phrases = tuple(dict.fromkeys(phrases))
        deduped_contains = tuple(dict.fromkeys(contains))
        if deduped_phrases or deduped_contains:
            matchers.append(
                CataloguePageMatcher(
                    dt_code=defn.code.strip().upper(),
                    phrases=deduped_phrases,
                    text_contains=deduped_contains,
                )
            )
    matchers.sort(key=lambda row: max((len(p) for p in row.phrases), default=0), reverse=True)
    return matchers


def infer_page_kind_token(
    page_text: str,
    *,
    matchers: list[CataloguePageMatcher] | None = None,
) -> str | None:
    """
    Return a stable page-kind token: ``kind:<heading>`` or ``dt:<code>``.
    Uses static heading detection first, then tenant catalogue matchers.
    """
    if is_continuation_page(page_text or ""):
        return None

    heading_kind = infer_page_document_kind(page_text or "")
    if heading_kind:
        return f"kind:{heading_kind}"

    blob = (page_text or "").lower()
    if not blob.strip():
        return None

    for matcher in matchers or []:
        for phrase in matcher.phrases:
            if phrase and phrase in blob:
                return f"dt:{matcher.dt_code}"
        for needle in matcher.text_contains:
            if needle and needle in blob:
                return f"dt:{matcher.dt_code}"
    return None


def heading_kind_from_token(token: str | None) -> str | None:
    if not token:
        return None
    if token.startswith("kind:"):
        return token[5:] or None
    return None
