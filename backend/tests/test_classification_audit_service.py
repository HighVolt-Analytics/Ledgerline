"""Tests for classification audit detail resolution."""

from types import SimpleNamespace

from datetime import datetime, timedelta

from app.services.classification.classification_audit_service import merge_classification_audit_detail


def _log(event: str, detail: dict, *, offset: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        event=event,
        detail=detail,
        created_at=datetime(2026, 6, 30, 12, 0, offset),
        id=offset,
    )


def test_merge_prefers_newest_gate_failed_over_older_gate_pass() -> None:
    invoice = SimpleNamespace(
        llm_suggested_dt=None,
        llm_confidence=0.15,
        document_type_code=None,
        document_type_confidence=None,
    )
    merged = merge_classification_audit_detail(
        invoice=invoice,
        logs=[
            _log(
                "classification_gate_failed",
                {
                    "llm_confidence": 0.15,
                    "llm_reasoning": "Latest: no catalogue match.",
                    "compare_passed": False,
                    "review_reasons": ["DT_NOT_IN_CATALOGUE", "LLM_LOW_CONF"],
                },
                offset=2,
            ),
            _log(
                "classification_gate_passed",
                {
                    "llm_confidence": 0.95,
                    "llm_reasoning": "Older pass.",
                    "compare_passed": True,
                    "review_reasons": [],
                },
                offset=1,
            ),
        ],
    )
    assert merged["llm_confidence"] == 0.15
    assert merged["llm_reasoning"] == "Latest: no catalogue match."
    assert merged["review_reasons"] == ["DT_NOT_IN_CATALOGUE", "LLM_LOW_CONF"]


def test_merge_prefers_gate_failed_when_document_classified_missing() -> None:
    invoice = SimpleNamespace(
        llm_suggested_dt=None,
        llm_confidence=0.15,
        document_type_code=None,
        document_type_confidence=None,
    )
    merged = merge_classification_audit_detail(
        invoice=invoice,
        logs=[
            _log(
                "classification_gate_failed",
                {
                    "llm_suggested_dt": None,
                    "llm_confidence": 0.15,
                    "llm_reasoning": "No catalogue match for contract.",
                    "compare_passed": False,
                    "review_reasons": ["DT_NOT_IN_CATALOGUE", "LLM_LOW_CONF"],
                },
            ),
            _log(
                "llm_classified",
                {
                    "llm_suggested_dt": "",
                    "llm_confidence": 0.15,
                    "llm_reasoning": "No catalogue match for contract.",
                    "document_ai_provider": "azure_di",
                },
            ),
        ],
    )
    assert merged["llm_confidence"] == 0.15
    assert merged["llm_reasoning"] == "No catalogue match for contract."
    assert merged["review_reasons"] == ["DT_NOT_IN_CATALOGUE", "LLM_LOW_CONF"]
    assert merged["compare_passed"] is False


def test_merge_uses_document_classified_when_present() -> None:
    invoice = SimpleNamespace(
        llm_suggested_dt="DT-03",
        llm_confidence=0.91,
        document_type_code="DT-03",
        document_type_confidence=0.91,
    )
    merged = merge_classification_audit_detail(
        invoice=invoice,
        logs=[
            _log(
                "document_classified",
                {
                    "llm_suggested_dt": "DT-03",
                    "policy_winner_dt": "DT-03",
                    "compare_passed": True,
                },
            ),
            _log("llm_classified", {"llm_suggested_dt": "DT-03", "llm_confidence": 0.91}),
        ],
    )
    assert merged["policy_winner_dt"] == "DT-03"
    assert merged["compare_passed"] is True


def test_merge_vision_map_sets_confirmed_and_live_invoice_wins() -> None:
    invoice = SimpleNamespace(
        llm_suggested_dt="DT-10",
        llm_confidence=1.0,
        document_type_code="DT-10",
        document_type_confidence=0.92,
    )
    merged = merge_classification_audit_detail(
        invoice=invoice,
        logs=[
            _log(
                "vision_document_type_mapped",
                {
                    "code": "DT-10",
                    "method": "llm_catalogue_fallback",
                    "confidence": 1.0,
                    "llm_reasoning": "Against advance form.",
                },
                offset=3,
            ),
            _log(
                "document_classified",
                {
                    "llm_suggested_dt": "DT-08",
                    "confirmed_dt": "DT-08",
                    "document_type_code": "DT-08",
                    "compare_passed": True,
                },
                offset=1,
            ),
        ],
    )
    assert merged["llm_suggested_dt"] == "DT-10"
    assert merged["confirmed_dt"] == "DT-10"
    assert merged["document_type_code"] == "DT-10"
