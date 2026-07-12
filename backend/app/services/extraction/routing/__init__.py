"""Document extraction routing: classify DT → extraction strategy."""

from __future__ import annotations

from app.services.extraction.routing.decision import DocumentRouteDecision
from app.services.extraction.routing.registry import get_extraction_strategy
from app.services.extraction.routing.router import route_document_for_extraction
from app.services.extraction.routing.routes import ExtractionRoute
from app.services.extraction.routing.strategy import (
    DocumentExtractionStrategy,
    ExtractionStrategyConfig,
    LayoutLineMode,
)

__all__ = [
    "DocumentExtractionStrategy",
    "DocumentRouteDecision",
    "ExtractionRoute",
    "ExtractionStrategyConfig",
    "LayoutLineMode",
    "get_extraction_strategy",
    "route_document_for_extraction",
]
