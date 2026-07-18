"""Phase 1: durable ingest_skipped reason taxonomy (alerting-ready)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.services.ingest.email_ingestion import EmailAttachment, RawEmail, _decode_attachment
from app.services.ingest.ingest_skip_service import (
    INGEST_SKIPPED_EVENT,
    REASON_ERROR_CLASS,
    error_class_for_reason,
    log_ingest_skip,
)
from app.services.invoice.pipeline import ingest_email_attachments
from app.tenant_ids import TESTING_TENANT_UUID


def test_integrity_and_failure_reasons_are_distinct() -> None:
    assert "ingest_integrity_error" != "ingest_message_failed"
    assert error_class_for_reason("ingest_integrity_error") == "integrity"
    assert error_class_for_reason("ingest_message_failed") == "failure"
    assert REASON_ERROR_CLASS["ingest_integrity_error"] == "integrity"
    assert REASON_ERROR_CLASS["ingest_message_failed"] == "failure"


def test_reason_taxonomy_alert_classes() -> None:
    assert error_class_for_reason("mailbox_token_failed") == "ops"
    assert error_class_for_reason("plan_channel_blocked") == "ops"
    assert error_class_for_reason("attachment_type_filtered") == "filter"
    assert error_class_for_reason("text_only") == "filter"
    assert error_class_for_reason("attachment_bytes_missing") == "data"
    assert error_class_for_reason("attachment_decode_failed") == "data"
    assert error_class_for_reason("mailbox_poll_failed") == "failure"
    assert error_class_for_reason("download_failed") == "failure"


@pytest.mark.asyncio
async def test_log_ingest_skip_writes_ingest_skipped(db_session: AsyncSession) -> None:
    await log_ingest_skip(
        db_session,
        reason="attachment_type_filtered",
        channel="email",
        tenant_id=TESTING_TENANT_UUID,
        message_id="<msg-1>",
        mailbox="ap@example.com",
        filename="logo.png",
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == INGEST_SKIPPED_EVENT)
        )
    ).scalars().all()
    assert len(rows) == 1
    detail = rows[0].detail or {}
    assert detail["reason"] == "attachment_type_filtered"
    assert detail["channel"] == "email"
    assert detail["error_class"] == "filter"
    assert detail["message_id"] == "<msg-1>"
    assert detail["mailbox"] == "ap@example.com"
    assert detail["filename"] == "logo.png"


def test_decode_attachment_drop_reasons() -> None:
    assert _decode_attachment({"@odata.type": "#microsoft.graph.itemAttachment"}) == (
        None,
        "attachment_not_file",
    )
    assert _decode_attachment(
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "inv.pdf",
            "contentBytes": None,
        }
    ) == (None, "attachment_bytes_missing")

    with patch(
        "app.services.ingest.email_ingestion.base64.b64decode",
        side_effect=ValueError("bad b64"),
    ):
        assert _decode_attachment(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "inv.pdf",
                "contentBytes": "!!!",
            }
        ) == (None, "attachment_decode_failed")


@pytest.mark.asyncio
async def test_pipeline_emits_distinct_integrity_vs_failure_skips(
    db_session: AsyncSession,
) -> None:
    """IntegrityError and generic Exception must never share the same reason string."""
    emails = [
        RawEmail(
            message_id="<integrity@example.com>",
            subject="Integrity",
            sender="vendor@example.com",
            mailbox_email="ap@example.com",
            attachments=[
                EmailAttachment(
                    filename="a.pdf",
                    content_type="application/pdf",
                    data=b"%PDF-1.4",
                )
            ],
        ),
        RawEmail(
            message_id="<failure@example.com>",
            subject="Failure",
            sender="vendor@example.com",
            mailbox_email="ap@example.com",
            attachments=[
                EmailAttachment(
                    filename="b.pdf",
                    content_type="application/pdf",
                    data=b"%PDF-1.4",
                )
            ],
        ),
    ]

    call_count = {"n": 0}

    async def _boom(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError("stmt", {}, Exception("dup"))
        raise RuntimeError("unexpected boom")

    with patch(
        "app.services.invoice.pipeline._ingest_single_email",
        new=AsyncMock(side_effect=_boom),
    ):
        result = await ingest_email_attachments(
            db_session,
            emails,
            tenant_id=TESTING_TENANT_UUID,
            tenant_slug="hv-org",
            known_message_ids=frozenset(),
            mark_processed=False,
        )

    assert result.preskip_exceptions["<integrity@example.com>"] == "integrity_error"
    assert result.preskip_exceptions["<failure@example.com>"] == "ingest_error"

    rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == INGEST_SKIPPED_EVENT)
        )
    ).scalars().all()
    reasons = {((r.detail or {}).get("reason")) for r in rows}
    error_classes = {((r.detail or {}).get("error_class")) for r in rows}
    assert "ingest_integrity_error" in reasons
    assert "ingest_message_failed" in reasons
    assert reasons & {"ingest_integrity_error", "ingest_message_failed"} == {
        "ingest_integrity_error",
        "ingest_message_failed",
    }
    assert "integrity" in error_classes
    assert "failure" in error_classes
    # Must never collapse both into one opaque reason.
    integrity_rows = [
        r for r in rows if (r.detail or {}).get("reason") == "ingest_integrity_error"
    ]
    failure_rows = [
        r for r in rows if (r.detail or {}).get("reason") == "ingest_message_failed"
    ]
    assert len(integrity_rows) == 1
    assert len(failure_rows) == 1
    assert (integrity_rows[0].detail or {}).get("error_class") == "integrity"
    assert (failure_rows[0].detail or {}).get("error_class") == "failure"
    assert (failure_rows[0].detail or {}).get("exc_type") == "RuntimeError"
