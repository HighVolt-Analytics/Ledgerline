"""Extraction strategy protocol and configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.routing.decision import DocumentRouteDecision
from app.services.extraction.routing.routes import ExtractionRoute

LayoutLineMode = Literal["gap_fill", "primary", "ignore"]


@dataclass(frozen=True)
class ExtractionStrategyConfig:
    name: str
    primary_model: str | None
    fallback_models: tuple[str, ...] = ()
    expect_line_items: bool = False
    totals_authoritative: bool = False
    layout_line_mode: LayoutLineMode = "ignore"
    layout_primary: bool = False
    allow_invoice_model: bool = False
    field_trust_min_confidence: float | None = None
    line_item_trust_min_confidence: float | None = None
    query_fields: tuple[str, ...] = ()
    custom_model_id: str | None = None
    review_on_unknown: bool = False
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class StrategyEnrichResult:
    ocr: OcrArtifact
    audit: dict[str, object]
    models_run: list[str] = field(default_factory=list)


class DocumentExtractionStrategy(Protocol):
    route: ExtractionRoute
    config: ExtractionStrategyConfig

    def enrich(
        self,
        ocr: OcrArtifact,
        file_path: Path,
        decision: DocumentRouteDecision,
    ) -> StrategyEnrichResult: ...
