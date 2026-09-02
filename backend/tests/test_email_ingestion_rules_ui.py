"""Email ingestion rules UI/API gap fixes."""

from app.schemas.rule_book_config import EmailCaptureAction, EmailCaptureRule, RuleCondition, RuleConditionGroup
from app.services.ingest.email_capture_rule_validation import validate_email_capture_rules_warnings_by_id
from app.services.ingest.email_ingestion_rules_service import normalize_email_capture_rules_for_save
from app.services.ingest.ingest_capture_service import (
    EMPLOYEE_BYPASS_CAPTURE_RULE_ID,
    capture_rule_requires_employee_sender,
    employee_bypass_capture_rule,
)


def test_normalize_sets_requires_employee_sender() -> None:
    rule = employee_bypass_capture_rule("*")
    assert rule.requires_employee_sender is True
    normalized = normalize_email_capture_rules_for_save([rule])
    assert normalized[0].requires_employee_sender is True


def test_persisted_requires_employee_sender_overrides_route() -> None:
    rule = EmailCaptureRule(
        id="ec-x",
        name="Custom",
        enabled=True,
        priority=1,
        mailbox="*",
        root=RuleConditionGroup(
            type="group",
            operator="AND",
            children=[
                RuleCondition(
                    type="condition",
                    field="subject",
                    operator="contains",
                    value="x",
                )
            ],
        ),
        action=EmailCaptureAction(save_attachment=True, route_to="Team Expenses", tags=[]),
        requires_employee_sender=False,
    )
    assert capture_rule_requires_employee_sender(rule) is False


def test_validate_warnings_by_id() -> None:
    rule = EmailCaptureRule(
        id="ec-dead",
        name="Dead",
        enabled=True,
        priority=1,
        mailbox="inbox@co.com",
        root=RuleConditionGroup(
            type="group",
            operator="AND",
            children=[
                RuleCondition(
                    type="condition",
                    field="subject",
                    operator="contains",
                    value="",
                )
            ],
        ),
        action=EmailCaptureAction(save_attachment=True, route_to="Purchase Management", tags=[]),
    )
    warnings = validate_email_capture_rules_warnings_by_id([rule])
    assert "ec-dead" in warnings
    assert warnings["ec-dead"]


def test_validate_disconnected_mailbox_warning() -> None:
    rule = EmailCaptureRule(
        id="ec-stale",
        name="Purchase test documents",
        enabled=True,
        priority=1,
        mailbox="vishnu@highvolt.tech",
        root=RuleConditionGroup(
            type="group",
            operator="AND",
            children=[
                RuleCondition(
                    type="condition",
                    field="from",
                    operator="contains",
                    value="test@example.com",
                )
            ],
        ),
        action=EmailCaptureAction(save_attachment=True, route_to="Purchase Management", tags=[]),
    )
    warnings = validate_email_capture_rules_warnings_by_id(
        [rule],
        connected_mailbox_emails={"mahendra@highvolt.tech"},
    )
    assert "ec-stale" in warnings
    assert any("not connected" in item for item in warnings["ec-stale"])


def test_employee_bypass_id_constant() -> None:
    assert employee_bypass_capture_rule("*").id == EMPLOYEE_BYPASS_CAPTURE_RULE_ID
