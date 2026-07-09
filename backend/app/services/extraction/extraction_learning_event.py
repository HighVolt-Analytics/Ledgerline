"""Extraction learning events from reviewer corrections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractionLearningEvent:
    org_id: str
    dt_code: str
    field_key: str
    before_value: Any
    after_value: Any
    ocr_snippet: str
    invoice_id: int | None = None


def build_learning_event(
    *,
    org_id: str,
    dt_code: str,
    field_key: str,
    before_value: Any,
    after_value: Any,
    ocr_snippet: str,
    invoice_id: int | None = None,
) -> ExtractionLearningEvent:
    return ExtractionLearningEvent(
        org_id=org_id,
        dt_code=dt_code,
        field_key=field_key,
        before_value=before_value,
        after_value=after_value,
        ocr_snippet=(ocr_snippet or "")[:400],
        invoice_id=invoice_id,
    )
