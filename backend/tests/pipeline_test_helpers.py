"""Shared monkeypatches for pipeline classification gate tests."""

from __future__ import annotations

import pytest

from app.services.invoice_pipeline_phases import GatePhaseResult


def patch_confidence_gate_pass(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dt: str = "DT-01",
    confidence: float = 0.95,
) -> None:
    """Force pre-extract confidence gate to pass (catalogue-independent)."""

    def _passing_gate(*_args, **_kwargs) -> GatePhaseResult:
        return GatePhaseResult(
            passed=True,
            confirmed_dt=dt,
            confirmed_confidence=confidence,
            review_reasons=[],
            llm_suggested_dt=dt,
            llm_confidence=confidence,
            llm_reasoning="test gate pass",
            min_route_confidence=0.85,
        )

    monkeypatch.setattr("app.services.pipeline.evaluate_confidence_gate", _passing_gate)
    monkeypatch.setattr(
        "app.services.pipeline.apply_user_defined_classifier_gate",
        lambda gate_result, **_kwargs: gate_result,
    )
