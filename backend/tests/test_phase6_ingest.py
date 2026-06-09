"""Phase 6: ingest capture + team expense validation."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.employee_master import EmployeeMasterRecord
from app.models.invoice import Invoice, InvoiceStatus
from app.services.email_ingestion import EmailAttachment, RawEmail
from app.services.ingest_capture_service import (
    apply_ingest_capture,
    evaluate_ingest_capture,
    raw_email_to_sample_email,
)
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice_evaluation_service import (
    ROUTE_TEAM,
    apply_invoice_evaluation,
    parse_matched_rule_ids,
)
from app.services.pipeline import ingest_email_attachments
from app.services.rule_book_mapper import clear_classification_config_cache
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.team_expense_validator import run_team_expense_validations
from app.services.validator import run_all_validations


@pytest.fixture
def capture_config() -> RuleBookConfigPayload:
    template = Path(__file__).resolve().parents[1] / "app" / "rule_book_config.json"
    return validate_rule_book_config_payload(json.loads(template.read_text(encoding="utf-8")))


@pytest.fixture
def clean_org_rule_book(tmp_path, monkeypatch: pytest.MonkeyPatch):
    upload = tmp_path / "uploads"
    rule_books = upload / "rule_books"
    rule_books.mkdir(parents=True)
    template = Path(__file__).resolve().parents[1] / "app" / "rule_book_config.json"
    shutil.copy2(template, rule_books / "1_config.json")
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    get_settings.cache_clear()
    clear_classification_config_cache()
    yield
    get_settings.cache_clear()
    clear_classification_config_cache()


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    clear_classification_config_cache()
    yield
    clear_classification_config_cache()


def _aws_billing_email() -> RawEmail:
    return RawEmail(
        message_id="msg-aws-1",
        subject="Your AWS invoice for May 2026",
        sender="billing@amazon.com",
        mailbox_email="accounts@acme-hospitality.com.au",
        attachments=[
            EmailAttachment(
                filename="AWS-Invoice-May.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.4 test",
            )
        ],
    )


def test_raw_email_to_sample_email_maps_fields() -> None:
    email = _aws_billing_email()
    sample = raw_email_to_sample_email(email, email.attachments[0])
    assert sample.from_addr == "billing@amazon.com"
    assert sample.subject == email.subject
    assert sample.attachment_name == "AWS-Invoice-May.pdf"


def test_evaluate_ingest_capture_matches_aws_rule(capture_config: RuleBookConfigPayload) -> None:
    email = _aws_billing_email()
    rule = evaluate_ingest_capture(email, email.attachments[0], capture_config)
    assert rule is not None
    assert rule.id == "ec-1"
    assert rule.action.route_to == "Purchase Management"


@pytest.mark.asyncio
async def test_apply_ingest_capture_persists_route(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    email = _aws_billing_email()
    inv = Invoice(org_id=1, status=InvoiceStatus.PENDING, file_hash="abc123")
    db_session.add(inv)
    await db_session.flush()

    rule = await apply_ingest_capture(
        db_session,
        inv,
        email,
        email.attachments[0],
        config=capture_config,
    )
    assert rule is not None
    assert inv.route_target == "Purchase Management"
    assert parse_matched_rule_ids(inv.matched_rule_ids) == ["email:ec-1"]
    assert inv.evaluation_status == "needs_review"


@pytest.mark.asyncio
async def test_ingest_email_attachments_sets_early_route(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    clean_org_rule_book,
) -> None:
    monkeypatch.setattr(
        "app.services.pipeline.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/test.pdf",
    )
    monkeypatch.setattr("app.services.pipeline._finish_email_message", lambda *args: None)

    result = await ingest_email_attachments(
        db_session,
        [_aws_billing_email()],
        org_id=1,
        org_slug="hv-org",
    )
    assert result.ingested_count == 1

    inv = (await db_session.execute(select(Invoice))).scalar_one()
    assert inv.route_target == "Purchase Management"
    assert "email:ec-1" in (inv.matched_rule_ids or "")


@pytest.mark.asyncio
async def test_apply_invoice_evaluation_preserves_ingest_email_route(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        status=InvoiceStatus.MAPPING,
        email_sender="billing@amazon.com",
        route_target="Purchase Management",
        matched_rule_ids='["email:ec-1"]',
        evaluation_status="needs_review",
    )
    db_session.add(inv)
    await db_session.flush()

    loaded = (
        await db_session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await apply_invoice_evaluation(db_session, loaded, config=capture_config)

    assert "email:ec-1" in parse_matched_rule_ids(inv.matched_rule_ids)
    assert inv.route_target == "Purchase Management"


@pytest.mark.asyncio
async def test_team_expense_budget_validation_fails(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    db_session.add(
        EmployeeMasterRecord(
            org_id=1,
            master_id="em-test",
            name="Site Supervisor",
            email="supervisor@acme-hospitality.com.au",
            budget={"monthly": 500.0, "quarterly": 1200.0, "annual": 4500.0, "categories": []},
            mtd_spent=480.0,
            status="Active",
            bank={"account_number": "12345678"},
        )
    )
    await db_session.flush()

    data = InvoiceData(
        vendor="Local Cafe",
        abn="51824753556",
        invoice_no="MEAL-001",
        invoice_date=None,
        due_date=None,
        total=Decimal("50.00"),
        line_items=[
            ParsedLineItem(description="Site supervisor lunch meal", amount=Decimal("50.00"))
        ],
    )
    results = await run_team_expense_validations(
        data,
        db_session,
        org_id=1,
        route_target=ROUTE_TEAM,
        email_sender="supervisor@acme-hospitality.com.au",
        config=capture_config,
    )
    by_rule = {row.rule: row for row in results}
    assert by_rule["VR-TE01"].passed
    assert not by_rule["VR-TE02"].passed
    assert "budget exceeded" in by_rule["VR-TE02"].message.lower()


@pytest.mark.asyncio
async def test_run_all_validations_skips_team_rules_for_purchase_route(
    db_session: AsyncSession,
    sample_invoice_data: InvoiceData,
) -> None:
    results = await run_all_validations(
        sample_invoice_data,
        db_session,
        org_id=1,
        route_target="Purchase Management",
    )
    assert not any(result.rule.startswith("VR-TE") for result in results)


@pytest.mark.asyncio
async def test_run_all_validations_includes_team_rules(
    db_session: AsyncSession,
    sample_invoice_data: InvoiceData,
) -> None:
    db_session.add(
        EmployeeMasterRecord(
            org_id=1,
            master_id="em-test-2",
            name="Ops Lead",
            email="ops@acme-hospitality.com.au",
            budget={"monthly": 5000.0, "quarterly": 12000.0, "annual": 45000.0, "categories": []},
            mtd_spent=100.0,
            status="Active",
            bank={"account_number": "12345678"},
        )
    )
    await db_session.flush()

    results = await run_all_validations(
        sample_invoice_data,
        db_session,
        org_id=1,
        sender="ops@acme-hospitality.com.au",
        route_target=ROUTE_TEAM,
    )
    team_rules = [result.rule for result in results if result.rule.startswith("VR-TE")]
    assert team_rules == [
        "VR-TE01",
        "VR-TE02",
        "VR-TE03",
        "VR-TE04",
        "VR-TE05",
        "VR-TE06",
    ]
