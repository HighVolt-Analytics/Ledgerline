"""Phase A: email capture gate, legacy cascade, upload routing."""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.email_ingestion import EmailAttachment, RawEmail
from app.services.legacy_cascade import legacy_rule_type, match_legacy_cascade
from app.services.invoice_evaluation_service import apply_invoice_evaluation
from app.services.pipeline import ingest_email_attachments
from app.services.rule_book_mapper import clear_classification_config_cache
from app.schemas.rule_book_config import validate_rule_book_config_payload


@pytest.fixture
def capture_config():
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


def _unmatched_email() -> RawEmail:
    return RawEmail(
        message_id="msg-unknown-1",
        subject="Hello team",
        sender="random@unknown.com",
        mailbox_email="accounts@acme-hospitality.com.au",
        attachments=[
            EmailAttachment(
                filename="note.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.4 other",
            )
        ],
    )


def test_legacy_cascade_vendor_match(capture_config) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Qantas Airways Limited",
        invoice_no="QAN-001",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = match_legacy_cascade(inv, capture_config.legacy_cascade)
    assert hit is not None
    assert hit[0] == "Travel Expense"


def test_legacy_cascade_po_code_match(capture_config) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Campaign Vendor",
        po_reference="PO-MKT-2026-014",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = match_legacy_cascade(inv, capture_config.legacy_cascade)
    assert hit is not None
    assert hit[0] == "Marketing Expense"


def test_legacy_cascade_maps_before_suspense(capture_config) -> None:
    from app.services.rule_book_mapper import resolve_config_mapping

    inv = Invoice(
        org_id=1,
        vendor="Hilton Sydney",
        invoice_no="HTL-LEGACY-1",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    hit = resolve_config_mapping(inv, capture_config)
    assert hit.rule_type == legacy_rule_type()
    assert hit.mapping.account_name == "Travel Expense"


def test_migrate_root_legacy_fields() -> None:
    raw = json.loads(
        (Path(__file__).resolve().parents[1] / "uploads" / "rule_books" / "1.json").read_text(
            encoding="utf-8"
        )
    )
    payload = validate_rule_book_config_payload(raw)
    assert payload.legacy_cascade.po_codes["PO-MKT-2026-014"] == "Marketing Expense"
    assert "AWS" in payload.legacy_cascade.keywords


@pytest.mark.asyncio
async def test_ingest_skips_email_without_capture_rule(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    clean_org_rule_book,
) -> None:
    monkeypatch.setattr("app.services.pipeline._finish_email_message", lambda *args: None)

    result = await ingest_email_attachments(
        db_session,
        [_unmatched_email()],
        org_id=1,
        org_slug="hv-org",
    )
    assert result.ingested_count == 0
    count = len((await db_session.execute(select(Invoice))).scalars().all())
    assert count == 0


@pytest.mark.asyncio
async def test_ingest_creates_invoice_when_capture_rule_matches(
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


@pytest.mark.asyncio
async def test_upload_routing_from_category_rules_after_parse(
    db_session: AsyncSession,
    capture_config,
) -> None:
    """Uploads without email metadata get route_target from purchase/expense rules."""
    inv = Invoice(
        org_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        status=InvoiceStatus.PARSING,
        currency="AUD",
        file_hash="upload-route-1",
    )
    db_session.add(inv)
    await db_session.flush()

    loaded = (
        await db_session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await apply_invoice_evaluation(db_session, loaded, config=capture_config)

    assert loaded.route_target == "Purchase Management"
    assert loaded.evaluation_status in {"auto_coded", "needs_review", "pending_vendor"}
