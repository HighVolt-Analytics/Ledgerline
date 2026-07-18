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
from app.services.ingest.email_ingestion import EmailAttachment, RawEmail
from app.services.ingest.ingest_capture_service import (
    apply_ingest_capture,
    evaluate_ingest_capture,
    raw_email_to_sample_email,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice.invoice_evaluation_service import (
    ROUTE_EXPENSES,
    ROUTE_TEAM,
    apply_invoice_evaluation,
    parse_matched_rule_ids,
)
from app.services.invoice.pipeline import ingest_email_attachments
from app.services.rule_book.rule_book_mapper import clear_classification_config_cache
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.purchase.team_expense_validator import run_team_expense_validations
from app.tenant_ids import TESTING_TENANT_UUID
from app.services.rule_book.validator import run_all_validations


@pytest.fixture
def clean_org_rule_book(tmp_path, monkeypatch: pytest.MonkeyPatch):
    upload = tmp_path / "uploads"
    rule_books = upload / "rule_books"
    rule_books.mkdir(parents=True)
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
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
async def test_apply_ingest_capture_records_ingest_rule_without_route(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    email = _aws_billing_email()
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING, file_hash="abc123")
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
    assert inv.route_target is None
    assert parse_matched_rule_ids(inv.matched_rule_ids) == ["ingest:ec-1"]
    assert inv.evaluation_status is None


@pytest.mark.asyncio
async def test_ingest_email_attachments_does_not_set_early_route(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    clean_org_rule_book,
) -> None:
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/test.pdf",
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._finish_email_message",
        lambda *args, **kwargs: None,
    )

    result = await ingest_email_attachments(
        db_session,
        [_aws_billing_email()],
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
    )
    assert result.ingested_count == 1

    inv = (await db_session.execute(select(Invoice))).scalar_one()
    assert inv.route_target is None
    assert "ingest:ec-1" in (inv.matched_rule_ids or "")


@pytest.mark.asyncio
async def test_apply_invoice_evaluation_preserves_ingest_email_route(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
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
async def test_apply_invoice_evaluation_preserves_email_route_over_po_reference(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    """Junk po_reference must not override email capture route_to on re-evaluation."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Qantas Airways Limited",
        invoice_no="QF-BOOK-3318745",
        po_reference="the",
        status=InvoiceStatus.MAPPING,
        route_target=ROUTE_EXPENSES,
        matched_rule_ids='["email:ec-1781011773259"]',
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

    assert "email:ec-1781011773259" in parse_matched_rule_ids(inv.matched_rule_ids)
    assert inv.route_target == ROUTE_EXPENSES


@pytest.mark.asyncio
async def test_team_expense_budget_validation_fails(
    db_session: AsyncSession,
    capture_config: RuleBookConfigPayload,
) -> None:
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
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
        tenant_id=TESTING_TENANT_UUID,
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
        tenant_id=TESTING_TENANT_UUID,
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
            tenant_id=TESTING_TENANT_UUID,
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
        tenant_id=TESTING_TENANT_UUID,
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


@pytest.fixture
def _enable_pdf_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF_MULTI_DOCUMENT_SPLIT", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ingest_email_attachments_keeps_mixed_bundle_as_one(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    clean_org_rule_book,
    _enable_pdf_split,
) -> None:
    from app.models.audit import AuditLog
    from app.services.extraction.pdf_page_text_service import PdfPageText, PdfPageTextExtraction

    pages = [
        PdfPageText(0, "PURCHASE ORDER\nPO Number: PO-9001\nVendor: Acme"),
        PdfPageText(1, "GOODS RECEIPT NOTE\nPO 9001\nReceived qty 10"),
        PdfPageText(2, "TAX INVOICE\nInvoice No: INV-9001\nTotal $110.00"),
    ]
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=pages),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/bundle.pdf",
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._finish_email_message",
        lambda *args, **kwargs: None,
    )

    email = _aws_billing_email()
    email.attachments[0] = EmailAttachment(
        filename="bundle.pdf",
        content_type="application/pdf",
        data=b"%PDF bundle",
    )
    result = await ingest_email_attachments(
        db_session,
        [email],
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
    )
    await db_session.flush()

    assert result.ingested_count == 1
    rows = (
        await db_session.execute(select(Invoice).where(Invoice.tenant_id == TESTING_TENANT_UUID))
    ).scalars().all()
    assert len(rows) == 1
    assert all(row.email_message_id == email.message_id for row in rows)

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "pdf_segmented")
        )
    ).scalars().all()
    assert len(audit) == 0
