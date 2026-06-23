"""Phase 7 — rule book completion (team GL, mailbox filter, MTD spend)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_master import EmployeeMasterRecord
from app.models.invoice import Invoice, InvoiceStatus
from app.services.email_ingestion import EmailAttachment, RawEmail
from app.services.ingest_capture_service import evaluate_ingest_capture
from app.services.rule_book_mapper import resolve_config_mapping
from app.schemas.rule_book_config import (
    EmailCaptureAction,
    EmailCaptureRule,
    RuleBookConfigPayload,
    RuleCondition,
    RuleConditionGroup,
    validate_rule_book_config_payload,
)
from app.services.rule_engine import SampleEmail, match_email_capture_rule
from app.services.team_expense_service import record_team_expense_processed


def test_expense_rule_wins_over_team_for_shared_vendor(capture_config: RuleBookConfigPayload) -> None:
    """Expenses route evaluates expense book only (team book is route-gated)."""
    inv = Invoice(
        tenant_id=1,
        vendor="Uber Australia",
        invoice_no="UBER-001",
        total=45.0,
        route_target="Expenses Management",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, capture_config)
    assert hit.rule_type == "Expense rule"
    assert hit.mapping.account_name == "Travel Expense"


def test_team_expense_rule_maps_ledger(capture_config: RuleBookConfigPayload) -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="Ola Cabs",
        invoice_no="OLA-001",
        total=45.0,
        route_target="Team Expenses",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, capture_config)
    assert hit.rule_type == "Team expense rule"
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
    assert evaluate_ingest_capture(email, email.attachments[0], capture_config) is None


@pytest.mark.asyncio
async def test_record_team_expense_processed_updates_mtd(db_session: AsyncSession) -> None:
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=1,
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
        tenant_id=1,
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
