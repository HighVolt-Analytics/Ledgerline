"""Rule engine unit tests (parity with frontend eval fixtures)."""

from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.rule_book_config_io import load_rule_book_config_dict
from app.services.rule_book_evaluate_service import sample_eval_documents
from app.services.rule_engine import (
    SampleEmail,
    build_live_evaluation,
    match_disabled_email_capture_rule,
    match_purchase_rule,
)


def test_sample_eval_aws_purchase_rule() -> None:
    config = validate_rule_book_config_payload(load_rule_book_config_dict(1))
    docs = sample_eval_documents()
    aws = docs[0]
    hit = match_purchase_rule(aws, config.purchase_rules)
    assert hit is not None
    assert hit.name == "Cloud & Hosting POs"


def test_build_live_evaluation_sample_rows() -> None:
    config = validate_rule_book_config_payload(load_rule_book_config_dict(1))
    rows = build_live_evaluation(sample_eval_documents(), config)
    assert len(rows) == 5
    aws_row = next(row for row in rows if row.doc.invoice_no == "AWS-AU-204815")
    assert aws_row.category_rule is not None
    assert aws_row.category_rule.kind == "Purchase"
    assert aws_row.category_rule.label == "Cloud & Hosting POs"
    sysco_row = next(row for row in rows if row.doc.invoice_no == "SYSCO-INV-88210")
    assert sysco_row.vendor.vendor is not None
    assert sysco_row.vendor.confidence > 0
    assert sysco_row.category_rule is not None


def test_match_disabled_email_capture_rule() -> None:
    from app.schemas.rule_book_config import (
        EmailCaptureAction,
        EmailCaptureRule,
        RuleCondition,
        RuleConditionGroup,
    )

    rule = EmailCaptureRule(
        id="ec-test",
        name="AWS billing",
        enabled=False,
        priority=1,
        mailbox="accounts@acme-hospitality.com.au",
        root=RuleConditionGroup(
            operator="AND",
            children=[
                RuleCondition(field="from", operator="contains", value="billing@amazon"),
                RuleCondition(field="subject", operator="contains", value="invoice"),
                RuleCondition(field="attachment_name", operator="ends_with", value=".pdf"),
            ],
        ),
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Purchase Management",
            tags=[],
        ),
        matched_count=0,
        last_matched="",
    )
    email = SampleEmail(
        id="sample-1",
        from_addr="billing@amazon.com",
        to="accounts@acme-hospitality.com.au",
        subject="Your AWS invoice",
        body="",
        attachment_name="invoice.pdf",
        attachment_mime="application/pdf",
    )
    hit = match_disabled_email_capture_rule(email, [rule])
    assert hit is not None
    assert hit.name == "AWS billing"
