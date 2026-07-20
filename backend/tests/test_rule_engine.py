"""Rule engine unit tests (parity with frontend eval fixtures)."""

import json
from pathlib import Path

from app.schemas.customer import CustomerMaster
from app.schemas.rule_book_config import (
    PostToAccounts,
    SalesMatchOn,
    SalesRule,
    validate_rule_book_config_payload,
)
from app.services.rule_book.rule_book_evaluate_service import _legacy_sample_eval_documents
from app.services.rule_book.rule_engine import (
    EvalDocument,
    SampleEmail,
    build_live_evaluation,
    detect_customer,
    match_disabled_email_capture_rule,
    match_purchase_rule,
)


def _template_config():
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    return validate_rule_book_config_payload(json.loads(template.read_text(encoding="utf-8")))


def test_sample_eval_aws_purchase_rule() -> None:
    config = _template_config()
    docs = _legacy_sample_eval_documents()
    aws = docs[0]
    hit = match_purchase_rule(aws, config.purchase_rules)
    assert hit is not None
    assert hit.name == "Cloud & Hosting POs"


def test_build_live_evaluation_sample_rows() -> None:
    config = _template_config()
    rows = build_live_evaluation(_legacy_sample_eval_documents(), config)
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


def test_microsoft_azure_invoice_test6_capture_rule() -> None:
    """Regression: attachment_name must end_with .pdf, not start_with."""
    from app.schemas.rule_book_config import (
        EmailCaptureAction,
        EmailCaptureRule,
        RuleCondition,
        RuleConditionGroup,
    )
    from app.services.rule_book.rule_engine import match_email_capture_rule

    rule = EmailCaptureRule(
        id="ec-azure",
        name="Microsoft Azure invoices",
        enabled=True,
        priority=130,
        mailbox="vishnu@highvolt.tech",
        root=RuleConditionGroup(
            operator="AND",
            children=[
                RuleCondition(field="attachment_name", operator="ends_with", value=".pdf"),
                RuleCondition(field="from", operator="contains", value="22je1038@iitism.ac.in"),
                RuleConditionGroup(
                    operator="OR",
                    children=[
                        RuleCondition(
                            field="attachment_name",
                            operator="contains",
                            value="invoice-test",
                        ),
                        RuleCondition(
                            field="attachment_name",
                            operator="contains",
                            value="azure",
                        ),
                        RuleCondition(field="subject", operator="contains", value="azure"),
                    ],
                ),
            ],
        ),
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Expenses Management",
            tags=[],
        ),
        matched_count=0,
        last_matched="",
    )
    email = SampleEmail(
        id="msg-azure-1",
        from_addr="22je1038@iitism.ac.in",
        to="vishnu@highvolt.tech",
        subject="azure invoice test",
        body="",
        attachment_name="invoice-test6.pdf",
        attachment_mime="application/pdf",
    )
    hit = match_email_capture_rule(email, [rule], mailbox="vishnu@highvolt.tech")
    assert hit is not None
    assert hit.action.route_to == "Expenses Management"


def test_subject_contains_mid_string_case_insensitive() -> None:
    """Regression: subject contains 'highvolt' must match 'vishnu works in highvolt'."""
    from app.schemas.rule_book_config import (
        EmailCaptureAction,
        EmailCaptureRule,
        RuleCondition,
        RuleConditionGroup,
        RuleBookConfigPayload,
    )
    from app.services.ingest.email_ingestion import EmailAttachment, RawEmail
    from app.services.ingest.ingest_capture_service import evaluate_ingest_capture
    from app.services.rule_book.rule_engine import match_email_capture_rule

    rule = EmailCaptureRule(
        id="ec-hv",
        name="Highvolt subject",
        enabled=True,
        priority=1,
        mailbox="*",
        root=RuleConditionGroup(
            operator="AND",
            children=[
                RuleCondition(field="subject", operator="contains", value="highvolt"),
            ],
        ),
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Purchase Management",
            tags=[],
        ),
    )
    email = SampleEmail(
        id="msg-hv",
        from_addr="sender@example.com",
        to="vishnu@highvolt.tech",
        subject="vishnu works in highvolt",
        body="",
        attachment_name="invoice.pdf",
        attachment_mime="application/pdf",
    )
    assert match_email_capture_rule(email, [rule], mailbox="vishnu@highvolt.tech") is not None

    # Trailing spaces in the rule value must not break contains.
    padded = rule.model_copy(
        update={
            "root": RuleConditionGroup(
                operator="AND",
                children=[
                    RuleCondition(field="subject", operator="contains", value="  highvolt  "),
                ],
            )
        }
    )
    assert match_email_capture_rule(email, [padded], mailbox="vishnu@highvolt.tech") is not None

    config = RuleBookConfigPayload(schema_version=1, email_capture_rules=[rule])
    raw = RawEmail(
        message_id="msg-hv",
        subject="vishnu works in highvolt",
        sender="sender@example.com",
        mailbox_email="vishnu@highvolt.tech",
        attachments=[
            EmailAttachment(
                filename="invoice.pdf",
                content_type="application/pdf",
                data=b"%PDF",
            )
        ],
    )
    assert evaluate_ingest_capture(raw, raw.attachments[0], config) is not None


def test_empty_nested_group_does_not_block_and_match() -> None:
    """UI can leave an empty nested group; backend must ignore it like the frontend."""
    from app.schemas.rule_book_config import (
        EmailCaptureAction,
        EmailCaptureRule,
        RuleCondition,
        RuleConditionGroup,
    )
    from app.services.rule_book.rule_engine import match_email_capture_rule

    rule = EmailCaptureRule(
        id="ec-empty-group",
        name="Subject with empty AND branch",
        enabled=True,
        priority=1,
        mailbox="*",
        root=RuleConditionGroup(
            operator="AND",
            children=[
                RuleCondition(field="subject", operator="contains", value="highvolt"),
                RuleConditionGroup(operator="AND", children=[]),
            ],
        ),
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Purchase Management",
            tags=[],
        ),
    )
    email = SampleEmail(
        id="msg-1",
        from_addr="sender@example.com",
        to="vishnu@highvolt.tech",
        subject="vishnu works in highvolt",
        body="",
        attachment_name="invoice.pdf",
        attachment_mime="application/pdf",
    )
    assert match_email_capture_rule(email, [rule], mailbox="vishnu@highvolt.tech") is not None


def test_starts_with_pdf_never_matches_real_filenames() -> None:
    from app.schemas.rule_book_config import (
        EmailCaptureAction,
        EmailCaptureRule,
        RuleCondition,
        RuleConditionGroup,
    )
    from app.services.rule_book.rule_engine import match_email_capture_rule

    broken = EmailCaptureRule(
        id="ec-broken",
        name="Broken pdf rule",
        enabled=True,
        priority=1,
        mailbox="vishnu@highvolt.tech",
        root=RuleConditionGroup(
            operator="AND",
            children=[
                RuleCondition(field="attachment_name", operator="starts_with", value=".pdf"),
                RuleCondition(field="from", operator="contains", value="22je1038@iitism.ac.in"),
            ],
        ),
        action=EmailCaptureAction(
            save_attachment=True,
            route_to="Expenses Management",
            tags=[],
        ),
        matched_count=0,
        last_matched="",
    )
    email = SampleEmail(
        id="msg-1",
        from_addr="22je1038@iitism.ac.in",
        to="vishnu@highvolt.tech",
        subject="test",
        body="",
        attachment_name="invoice-test6.pdf",
        attachment_mime="application/pdf",
    )
    assert match_email_capture_rule(email, [broken], mailbox="vishnu@highvolt.tech") is None


def test_build_live_evaluation_sales_uses_customer_match() -> None:
    config = validate_rule_book_config_payload(
        {
            "schema_version": 1,
            "sales_rules": [
                SalesRule(
                    id="sr-harbour",
                    name="New sales rule",
                    enabled=True,
                    priority=100,
                    match_on=SalesMatchOn(customer_contains="Harbour View"),
                    post_to=PostToAccounts(ledger="Operating Expenses"),
                ).model_dump(),
            ],
        }
    )
    doc = EvalDocument(
        id="201",
        doc_number="DOC-27",
        invoice_no="INV-9001",
        vendor="Harbour View Hotel",
        route_target="Sales Management",
        document_type="invoice",
    )
    customer = CustomerMaster(
        id="cm-harbour",
        name="Harbour View Hotel",
        aliases=["Harbour View"],
    )
    rows = build_live_evaluation([doc], config, customer_masters=[customer])
    assert len(rows) == 1
    row = rows[0]
    assert row.category_rule is not None
    assert row.category_rule.kind == "Sales"
    assert row.customer is not None
    assert row.customer.customer is not None
    assert row.customer.customer.name == "Harbour View Hotel"
    assert row.matched is True
    assert detect_customer(doc, [customer], config.vendor_detection_config).customer is not None
