"""Field fusion engine tests."""

from __future__ import annotations

from app.services.extraction.field_fusion_engine import fuse_scalar_field


def test_di_wins_over_llm_when_configured_priority() -> None:
    result = fuse_scalar_field(
        "total",
        {"llm": "500.00", "azure_di": "500.00"},
        dt_definition=None,
    )
    assert result is not None
    assert result.source == "azure_di"
    assert result.agreement_score == 1.0


def test_disagreement_lowers_agreement_score() -> None:
    result = fuse_scalar_field(
        "total",
        {"llm": "500.00", "azure_di": "600.00"},
        dt_definition=None,
    )
    assert result is not None
    assert result.agreement_score < 1.0
