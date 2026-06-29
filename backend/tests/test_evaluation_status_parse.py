"""EvaluationStatus parsing for classify-me gate."""

from app.schemas.invoice import EvaluationStatus, parse_evaluation_status


def test_parse_needs_rescan() -> None:
    assert parse_evaluation_status("needs_rescan") == EvaluationStatus.NEEDS_RESCAN


def test_parse_awaiting_classification() -> None:
    assert parse_evaluation_status("awaiting_classification") == (
        EvaluationStatus.AWAITING_CLASSIFICATION
    )


def test_parse_unknown_falls_back_to_needs_review() -> None:
    assert parse_evaluation_status("legacy_unknown") == EvaluationStatus.NEEDS_REVIEW


def test_parse_none() -> None:
    assert parse_evaluation_status(None) is None
