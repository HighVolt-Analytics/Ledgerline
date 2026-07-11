"""Configurable thresholds for line-item text parsing heuristics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LineItemParsingThresholds:
    min_row_length: int = 8
    min_qty_only_row_length: int = 4
    min_desc_length_tail_row: int = 4
    min_desc_length_qty_only: int = 3
    min_charge_desc_length: int = 3
    max_charge_desc_length: int = 200
    max_plausible_qty: Decimal = Decimal("10000")
    year_min: int = 1900
    year_max: int = 2099
    desc_match_prefix_len: int = 24
    llm_line_item_confidence_threshold: float = 0.85
    line_item_review_confidence_threshold: float = 0.75


DEFAULT_THRESHOLDS = LineItemParsingThresholds()


@dataclass(frozen=True)
class LineItemExtractionSettings:
    """Consolidated runtime settings for line-item extraction."""

    thresholds: LineItemParsingThresholds = DEFAULT_THRESHOLDS
    use_citation_grounding: bool = False
    runtime_llm_min_confidence: float = 0.0
    ocr_min_text_chars: int = 80
    azure_di_model_id: str = "prebuilt-invoice"
    azure_di_layout_model_id: str = "prebuilt-layout"
    runtime_line_item_trace_enabled: bool = False
    use_field_fusion: bool = False


def load_line_item_extraction_settings() -> LineItemExtractionSettings:
    from app.config import get_settings

    settings = get_settings()
    return LineItemExtractionSettings(
        thresholds=DEFAULT_THRESHOLDS,
        use_citation_grounding=settings.use_citation_grounding,
        runtime_llm_min_confidence=settings.runtime_llm_min_confidence,
        ocr_min_text_chars=settings.ocr_min_text_chars,
        azure_di_model_id=settings.azure_di_model_id,
        azure_di_layout_model_id=settings.azure_di_layout_model_id,
        runtime_line_item_trace_enabled=settings.runtime_line_item_trace_enabled,
        use_field_fusion=settings.use_field_fusion,
    )
