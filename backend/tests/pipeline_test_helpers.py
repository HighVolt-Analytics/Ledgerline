"""Shared monkeypatches for pipeline classification gate tests."""

from __future__ import annotations

import pytest

from app.services.invoice.file_validity_gate import FileValidityResult
from app.services.invoice.image_quality_gate import ImageQualityResult
from app.services.invoice.invoice_pipeline_phases import GatePhaseResult
from app.services.invoice.layout_readiness import LayoutReadinessResult, OcrMode
from app.services.invoice.vision_understand_gate import VisionUnderstandResult


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

    monkeypatch.setattr("app.services.invoice.pipeline.evaluate_confidence_gate", _passing_gate)
    monkeypatch.setattr(
        "app.services.invoice.pipeline.apply_recognition_mode_gate",
        lambda gate_result, **_kwargs: gate_result,
    )


def patch_pre_ocr_gates_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real file/visual/layout probes for minimal PDF fixtures."""

    def _passing_file_validity(_path: str) -> FileValidityResult:
        return FileValidityResult(passed=True, file_size_bytes=128)

    def _passing_image_quality(_path, **_kwargs) -> ImageQualityResult:
        return ImageQualityResult(passed=True, severity="pass", page_count_checked=1)

    def _standard_layout(_path) -> LayoutReadinessResult:
        return LayoutReadinessResult(
            ocr_mode=OcrMode.STANDARD_DI,
            allow_di_fallback=False,
            page_count=1,
            reasons=["test_default"],
        )

    async def _cannot_understand(*_args, **_kwargs) -> VisionUnderstandResult:
        return VisionUnderstandResult(
            can_understand=False,
            confidence=0.1,
            reason="test_legacy_path",
            provider="azure_di",
            fail_closed=True,
        )

    monkeypatch.setattr(
        "app.services.invoice.file_validity_gate.evaluate_file_validity",
        _passing_file_validity,
    )
    monkeypatch.setattr(
        "app.services.invoice.image_quality_gate.evaluate_pre_ocr_image_quality",
        _passing_image_quality,
    )
    monkeypatch.setattr(
        "app.services.invoice.layout_readiness.evaluate_layout_readiness",
        _standard_layout,
    )
    monkeypatch.setattr(
        "app.services.invoice.vision_understand_gate.evaluate_vision_understand",
        _cannot_understand,
    )
