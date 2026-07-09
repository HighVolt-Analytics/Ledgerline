"""Classification gap event tests."""

from __future__ import annotations

from app.services.classification.classification_gap_event import build_classification_gap_event


def test_build_gap_event_truncates_snippet() -> None:
    event = build_classification_gap_event(
        org_id="org-1",
        invoice_id=42,
        ocr_text="x" * 1000,
        candidates=[{"code": "DT-01", "confidence": 0.4}],
        chosen_dt="unknown_or_new_type",
    )
    assert len(event.ocr_snippet) <= 500
    assert event.top_candidates[0]["code"] == "DT-01"
