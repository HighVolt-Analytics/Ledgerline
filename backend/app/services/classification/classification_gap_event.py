"""Classification gap events for unknown/low-confidence document types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClassificationGapEvent:
    org_id: str
    invoice_id: int
    ocr_snippet: str
    top_candidates: list[dict[str, Any]]
    chosen_dt: str
    reviewer_override: str | None = None
    pipeline_run_id: str | None = None


def build_classification_gap_event(
    *,
    org_id: str,
    invoice_id: int,
    ocr_text: str,
    candidates: list[dict[str, Any]],
    chosen_dt: str,
    pipeline_run_id: str | None = None,
) -> ClassificationGapEvent:
    snippet = (ocr_text or "")[:500]
    return ClassificationGapEvent(
        org_id=org_id,
        invoice_id=invoice_id,
        ocr_snippet=snippet,
        top_candidates=candidates[:3],
        chosen_dt=chosen_dt,
        pipeline_run_id=pipeline_run_id,
    )


def gap_event_audit_detail(event: ClassificationGapEvent) -> dict[str, object]:
    return {
        "org_id": event.org_id,
        "invoice_id": event.invoice_id,
        "ocr_snippet": event.ocr_snippet,
        "top_candidates": event.top_candidates,
        "chosen_dt": event.chosen_dt,
        "pipeline_run_id": event.pipeline_run_id,
    }
