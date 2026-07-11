"""Tests for approval policy schema sync in rule book config."""

from app.schemas.rule_book_config import validate_rule_book_config_payload


def test_sync_match_policy_preserves_approval_risk_fields() -> None:
    payload = validate_rule_book_config_payload(
        {
            "document_types": [
                {
                    "code": "DT-07",
                    "title": "Standard invoice",
                    "shortTitle": "Invoice",
                    "klass": "Transactional",
                    "posting": "Yes",
                    "recognition_mode": "signals",
                    "recognition_signals": ["heading_invoice"],
                    "llm_prompt": "",
                    "routeTarget": "Purchase Management",
                    "playbook_profile": "po_goods",
                    "match_policy": {"mode": "two_way_po_ses"},
                    "approval_policy": {
                        "mode": "touchless_on_clean_match",
                        "auto_approve_below": 2500,
                        "require_approval_for_unmatched": True,
                        "require_approval_for_unverified_counterparty": True,
                    },
                }
            ]
        }
    )
    approval = payload.document_types[0].approval_policy
    assert approval is not None
    assert approval.mode == "touchless_on_clean_match"
    assert approval.auto_approve_below == 2500
    assert approval.require_approval_for_unmatched is True
    assert approval.require_approval_for_unverified_counterparty is True
