"""Pluggable document classifier port (Azure custom classifier ready)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.routing.decision import DocumentRouteDecision


class DocumentClassifierPort(Protocol):
    """Optional upstream classifier; return None to fall through to DT map."""

    def classify(
        self,
        file_path: Path,
        *,
        confirmed_dt: str,
        dt_definition: DocumentTypeDefinition | None,
        ocr: OcrArtifact | None = None,
    ) -> DocumentRouteDecision | None: ...


class NullDocumentClassifier:
    """Default: no Azure custom classifier wired yet."""

    def classify(
        self,
        file_path: Path,
        *,
        confirmed_dt: str,
        dt_definition: DocumentTypeDefinition | None,
        ocr: OcrArtifact | None = None,
    ) -> DocumentRouteDecision | None:
        return None


_default_classifier: DocumentClassifierPort = NullDocumentClassifier()


def get_document_classifier() -> DocumentClassifierPort:
    return _default_classifier


def set_document_classifier(classifier: DocumentClassifierPort) -> None:
    """Test/hook: replace the global classifier port."""
    global _default_classifier
    _default_classifier = classifier
