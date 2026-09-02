"""Deny-by-default email capture rule behavior."""

from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.ingest.email_ingestion import EmailAttachment, RawEmail
from app.services.ingest.email_capture_rule_validation import validate_rule_specificity
from app.services.ingest.ingest_capture_service import (
    EMPLOYEE_BYPASS_CAPTURE_RULE_ID,
    employee_bypass_capture_rule,
    ensure_email_capture_rules_in_dict,
    evaluate_ingest_capture,
)
from app.services.rule_book.rule_engine import _match_value


def test_evaluate_returns_none_when_no_enabled_rules() -> None:
    config = RuleBookConfigPayload(email_capture_rules=[])
    email = RawEmail(
        message_id="m1",
        subject="Invoice",
        sender="a@b.com",
        mailbox_email="inbox@co.com",
        attachments=[
            EmailAttachment(filename="inv.pdf", content_type="application/pdf", data=b"x")
        ],
    )
    assert evaluate_ingest_capture(email, email.attachments[0], config) is None


def test_empty_contains_never_matches() -> None:
    assert _match_value("hello", "contains", "") is False
    assert _match_value("hello", "starts_with", "") is False
    assert _match_value("hello", "ends_with", "") is False


def test_validate_rule_specificity_flags_empty_contains() -> None:
    rule = employee_bypass_capture_rule("*")
    rule = rule.model_copy(
        update={
            "root": {
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "condition",
                        "field": "subject",
                        "operator": "contains",
                        "value": "",
                    }
                ],
            }
        }
    )
    warnings = validate_rule_specificity(rule)
    assert any("empty value" in w for w in warnings)


def test_ensure_email_capture_rules_injects_employee_rule() -> None:
    data = ensure_email_capture_rules_in_dict({"email_capture_rules": []})
    assert data["email_capture_rules"][0]["id"] == EMPLOYEE_BYPASS_CAPTURE_RULE_ID
