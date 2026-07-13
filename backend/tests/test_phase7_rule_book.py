"""Phase 7 — rule book completion (document-type GL, mailbox filter, MTD spend)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_master import EmployeeMasterRecord
from app.models.invoice import Invoice, InvoiceStatus
from app.services.ingest.email_ingestion import EmailAttachment, RawEmail
from app.services.ingest.ingest_capture_service import evaluate_ingest_capture
from app.services.rule_book.rule_book_mapper import DOCUMENT_TYPE_RULE_TYPE, resolve_config_mapping
from app.schemas.rule_book_config import (
    EmailCaptureAction,
    EmailCaptureRule,
    RuleBookConfigPayload,
    RuleCondition,
    RuleConditionGroup,
)
from app.services.rule_book.rule_engine import SampleEmail, diagnose_email_capture_match, match_email_capture_rule
from app.services.purchase.team_expense_service import record_team_expense_processed
from app.tenant_ids import TESTING_TENANT_UUID


def test_expense_document_type_maps_operating_expenses(capture_config: RuleBookConfigPayload) -> None:
    """Direct expense document type (DT-08) maps via Post to, not expense GL rules."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Uber Australia",
        invoice_no="UBER-001",
        total=45.0,
        route_target="Expenses Management",
        document_type_code="DT-08",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, capture_config)
    assert hit.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert hit.mapping.account_name == "Operating Expenses"


def test_team_document_type_maps_travel_expense(capture_config: RuleBookConfigPayload) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Ola Cabs",
        invoice_no="OLA-001",
        total=45.0,
        route_target="Team Expenses",
        document_type_code="DT-12",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, capture_config)
    assert hit.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert hit.mapping.account_name == "Travel Expense"


def test_email_capture_respects_mailbox() -> None:
    email = SampleEmail(
        id="1",
        from_addr="billing@amazon.com",
        to="other@example.com",
        subject="AWS invoice May",
        body="",
        attachment_name="inv.pdf",
        attachment_mime="application/pdf",
    )
    rule = EmailCaptureRule(
        id="ec-test",
        name="AWS",
        priority=1,
        mailbox="accounts@acme-hospitality.com.au",
        root=RuleConditionGroup(
            operator="AND",
            children=[
                RuleCondition(field="from", operator="contains", value="amazon"),
            ],
        ),
        action=EmailCaptureAction(route_to="Purchase Management"),
    )
    assert match_email_capture_rule(email, [rule], mailbox="other@example.com") is None
    assert match_email_capture_rule(email, [rule], mailbox="accounts@acme-hospitality.com.au") is not None


def test_diagnose_email_capture_match_explains_rule_checks(capture_config: RuleBookConfigPayload) -> None:
    email = SampleEmail(
        id="msg-1",
        from_addr="billing@amazon.com",
        to="accounts@acme-hospitality.com.au",
        subject="Your AWS invoice for May 2026",
        body="",
        attachment_name="AWS-Invoice-May.pdf",
        attachment_mime="application/pdf",
    )
    diagnosis = diagnose_email_capture_match(
        email,
        capture_config.email_capture_rules,
        mailbox="accounts@acme-hospitality.com.au",
    )
    assert diagnosis["matched_rule_id"] == "ec-1"
    assert diagnosis["enabled_rule_count"] >= 1
    assert any(check["rule_id"] == "ec-1" and check["conditions_ok"] for check in diagnosis["rule_checks"])


def test_ingest_capture_skips_wrong_mailbox(capture_config: RuleBookConfigPayload) -> None:
    email = RawEmail(
        message_id="x",
        subject="Your AWS invoice for May 2026",
        sender="billing@amazon.com",
        mailbox_email="wrong@example.com",
        attachments=[
            EmailAttachment(
                filename="AWS-Invoice-May.pdf",
                content_type="application/pdf",
                data=b"%PDF",
            )
        ],
    )
    explicit_mailbox_rule = capture_config.email_capture_rules[0].model_copy(
        update={"mailbox": "accounts@other-company.com.au"},
    )
    scoped_config = capture_config.model_copy(
        update={"email_capture_rules": [explicit_mailbox_rule]},
    )
    assert evaluate_ingest_capture(email, email.attachments[0], scoped_config) is None


def test_ingest_capture_matches_legacy_placeholder_mailbox(
    capture_config: RuleBookConfigPayload,
) -> None:
    """Demo/default mailbox placeholder applies to any connected mailbox at ingest."""
    email = RawEmail(
        message_id="x",
        subject="Your AWS invoice for May 2026",
        sender="billing@amazon.com",
        mailbox_email="vishnu@highvolt.tech",
        attachments=[
            EmailAttachment(
                filename="AWS-Invoice-May.pdf",
                content_type="application/pdf",
                data=b"%PDF",
            )
        ],
    )
    rule = evaluate_ingest_capture(email, email.attachments[0], capture_config)
    assert rule is not None
    assert rule.id == "ec-1"


@pytest.mark.asyncio
async def test_record_team_expense_processed_updates_mtd(db_session: AsyncSession) -> None:
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-ops",
            name="Ops Lead",
            email="ops@acme-hospitality.com.au",
            budget={"monthly": 5000, "quarterly": 12000, "annual": 45000, "categories": []},
            mtd_spent=100.0,
            ytd_spent=500.0,
            claim_count=2,
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Local Cafe",
        invoice_no="MEAL-99",
        total=50.0,
        email_sender="ops@acme-hospitality.com.au",
        route_target="Team Expenses",
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()

    await record_team_expense_processed(db_session, inv)

    row = (
        await db_session.execute(
            select(EmployeeMasterRecord).where(EmployeeMasterRecord.master_id == "em-ops")
        )
    ).scalar_one()
    assert row.mtd_spent == 150.0
    assert row.ytd_spent == 550.0
    assert row.claim_count == 3
