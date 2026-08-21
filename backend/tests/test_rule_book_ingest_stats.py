"""Email capture ingest stats derived from audit_logs."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.services.audit.audit_service import log_event
from app.services.ingest.ingest_capture_service import apply_ingest_capture
from app.services.rule_book.rule_book_ingest_stats import (
    attach_email_capture_ingest_stats,
    load_email_capture_ingest_stats,
    month_start_utc,
    strip_email_capture_volatile_stats,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.services.ingest.email_ingestion import EmailAttachment, RawEmail
from app.tenant_ids import TESTING_TENANT_UUID
from tests.rule_book_fixtures import load_capture_config


def _aws_email() -> RawEmail:
    return RawEmail(
        message_id="msg-stats-1",
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


@pytest.mark.asyncio
async def test_load_ingest_stats_counts_current_month_only(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    rule_id = "ec-1"

    db_session.add_all(
        [
            AuditLog(
                tenant_id=TESTING_TENANT_UUID,
                event="ingest_capture_matched",
                detail={"rule_id": rule_id, "rule_name": "AWS"},
                created_at=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
            ),
            AuditLog(
                tenant_id=TESTING_TENANT_UUID,
                event="ingest_capture_matched",
                detail={"rule_id": rule_id, "rule_name": "AWS"},
                created_at=datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc),
            ),
            AuditLog(
                tenant_id=TESTING_TENANT_UUID,
                event="ingest_capture_matched",
                detail={"rule_id": rule_id, "rule_name": "AWS"},
                created_at=datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    await db_session.flush()

    stats = await load_email_capture_ingest_stats(
        db_session,
        TESTING_TENANT_UUID,
        now=now,
    )
    assert stats[rule_id].matched_count == 2
    assert stats[rule_id].last_matched.endswith("ago")


@pytest.mark.asyncio
async def test_load_ingest_stats_groups_in_sql(
    db_session: AsyncSession,
) -> None:
    from sqlalchemy import event

    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="ingest_capture_matched",
            detail={"rule_id": "ec-sql", "rule_name": "SQL"},
        )
    )
    await db_session.flush()

    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def _before(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(str(statement))

    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        await load_email_capture_ingest_stats(db_session, TESTING_TENANT_UUID)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)

    joined = " ".join(statements).lower()
    assert "group by" in joined
    assert "audit_logs" in joined


@pytest.mark.asyncio
async def test_attach_ingest_stats_overlays_config(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="ingest_capture_matched",
            detail={"rule_id": "ec-foo", "rule_name": "Test"},
            created_at=now - timedelta(hours=2),
        )
    )
    await db_session.flush()

    config = {
        "email_capture_rules": [
            {
                "id": "ec-foo",
                "name": "Test",
                "matched_count": 999,
                "last_matched": "stale",
            },
            {"id": "ec-empty", "name": "Empty"},
        ]
    }
    await attach_email_capture_ingest_stats(
        db_session,
        TESTING_TENANT_UUID,
        config,
        now=now,
    )
    assert config["email_capture_rules"][0]["matched_count"] == 1
    assert config["email_capture_rules"][0]["last_matched"] == "2h ago"
    assert config["email_capture_rules"][1]["matched_count"] == 0
    assert config["email_capture_rules"][1]["last_matched"] == "—"


def test_strip_volatile_stats_removes_server_fields() -> None:
    data = {
        "email_capture_rules": [
            {"id": "ec-1", "matched_count": 12, "last_matched": "1h ago"},
        ]
    }
    strip_email_capture_volatile_stats(data)
    assert "matched_count" not in data["email_capture_rules"][0]
    assert "last_matched" not in data["email_capture_rules"][0]


def test_month_start_utc() -> None:
    assert month_start_utc(datetime(2026, 6, 24, 15, 30, tzinfo=timezone.utc)) == datetime(
        2026, 6, 1, 0, 0, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_apply_ingest_capture_feeds_stats(
    db_session: AsyncSession,
    capture_config,
) -> None:
    email = _aws_email()
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING, file_hash="stats-hash")
    db_session.add(inv)
    await db_session.flush()

    await apply_ingest_capture(
        db_session,
        inv,
        email,
        email.attachments[0],
        config=capture_config,
    )
    await db_session.flush()

    stats = await load_email_capture_ingest_stats(db_session, TESTING_TENANT_UUID)
    assert stats["ec-1"].matched_count == 1
    assert stats["ec-1"].last_matched in {"just now", "1m ago"}
