"""Composite confidence scoring for routing decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompositeScoreResult:
    composite_score: float
    routing_decision: str
    factors: dict[str, float]


def score_composite_confidence(
    *,
    ocr_sparse: bool = False,
    citation_failed_count: int = 0,
    self_consistency_disagreements: int = 0,
    validation_passed: bool = True,
    dt_confidence: float = 0.9,
    fusion_agreement_avg: float = 1.0,
) -> CompositeScoreResult:
    score = 1.0
    factors: dict[str, float] = {}
    if ocr_sparse:
        score -= 0.2
        factors["ocr_sparse"] = -0.2
    if citation_failed_count:
        penalty = min(0.5, 0.15 * citation_failed_count)
        score -= penalty
        factors["citation_failed"] = -penalty
    if self_consistency_disagreements:
        penalty = min(0.3, 0.1 * self_consistency_disagreements)
        score -= penalty
        factors["self_consistency"] = -penalty
    if not validation_passed:
        score -= 0.4
        factors["validation"] = -0.4
    score *= max(0.0, min(1.0, dt_confidence))
    factors["dt_confidence_multiplier"] = max(0.0, min(1.0, dt_confidence))
    score *= max(0.0, min(1.0, fusion_agreement_avg))
    factors["fusion_agreement_multiplier"] = max(0.0, min(1.0, fusion_agreement_avg))
    score = max(0.0, min(1.0, score))
    if score >= 0.85 and validation_passed and citation_failed_count == 0:
        decision = "auto_process"
    elif score >= 0.6:
        decision = "supervisor_review"
    else:
        decision = "needs_rescan"
    return CompositeScoreResult(
        composite_score=score,
        routing_decision=decision,
        factors=factors,
    )
