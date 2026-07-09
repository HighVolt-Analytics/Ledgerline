"""Composite confidence scorer tests."""

from __future__ import annotations

from app.services.extraction.composite_confidence_scorer import score_composite_confidence


def test_citation_failure_forces_review() -> None:
    result = score_composite_confidence(citation_failed_count=2, validation_passed=True)
    assert result.routing_decision in {"supervisor_review", "needs_rescan"}
    assert result.composite_score < 0.85


def test_clean_invoice_auto_process() -> None:
    result = score_composite_confidence(validation_passed=True, dt_confidence=0.95)
    assert result.routing_decision == "auto_process"
