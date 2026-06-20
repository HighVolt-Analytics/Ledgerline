"""Unit tests for dossier 15-stage pipeline builder."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier_pipeline_service import STAGE_IDS, build_dossier_pipeline, first_pipeline_failure


def _log(event: str, invoice_id: int, **detail: object) -> AuditLog:
    return AuditLog(
        event=event,
        invoice_id=invoice_id,
        created_at=datetime.now(timezone.utc),
        detail=dict(detail),
    )


@pytest.mark.asyncio
async def test_pipeline_always_fifteen_stages(db_session: AsyncSession) -> None:
    inv = Invoice(org_id=1, vendor="Acme", status=InvoiceStatus.PENDING)
    db_session.add(inv)
    await db_session.flush()
    pipeline = build_dossier_pipeline(inv, [])
    assert len(pipeline) == 15
    assert [step.stage_id for step in pipeline] == list(STAGE_IDS)


@pytest.mark.asyncio
async def test_pipeline_processed_invoice_full_pass(db_session: AsyncSession) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Meridian Foods",
        invoice_no="INV-100",
        document_type_code="DT-01",
        document_type_confidence=0.97,
        account_name="5100 Food inventory",
        account_code="5100",
        status=InvoiceStatus.PROCESSED,
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        validation_results='[{"rule":"VR01","passed":true,"message":"Total OK"}]',
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log("invoice_uploaded", inv.id),
        _log("parse_completed", inv.id, confidence=97),
        _log("document_classified", inv.id, document_type_code="DT-01"),
        _log("playbook_evaluated", inv.id, blocks_posting=False),
        _log("validation_passed", inv.id),
        _log("mapping_applied", inv.id, account_name="5100 Food inventory", rule_type="purchase_rule"),
        _log("invoice_processed", inv.id, route_target="purchases"),
    ]
    pipeline = build_dossier_pipeline(inv, logs, payment_status="awaiting", payment_detail="Awaiting payment")

    passed = [s for s in pipeline if s.state == "pass"]
    assert len(passed) >= 10
    assert pipeline[0].stage_id == "ingest" and pipeline[0].state == "pass"
    assert pipeline[12].stage_id == "post" and pipeline[12].state == "pass"
    assert pipeline[6].stage_id == "validate" and pipeline[6].checks
    assert first_pipeline_failure(pipeline) is None


@pytest.mark.asyncio
async def test_pipeline_duplicate_blocks_downstream(db_session: AsyncSession) -> None:
    inv = Invoice(org_id=1, vendor="Acme", status=InvoiceStatus.DUPLICATE_SKIPPED, file_hash="x")
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log("email_ingested", inv.id),
        _log("duplicate_skipped", inv.id, reason="hash match"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    fail = first_pipeline_failure(pipeline)
    assert fail is not None
    assert fail.stage_id == "duplicate"
    extract = next(s for s in pipeline if s.stage_id == "extract")
    assert extract.state == "pending"
    assert extract.blocked_reason and extract.blocked_reason.startswith("Blocked —")


@pytest.mark.asyncio
async def test_pipeline_map_gl_without_audit_log(db_session: AsyncSession) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Acme",
        status=InvoiceStatus.MAPPING,
        account_name="5100 Food inventory",
        account_code="5100",
    )
    db_session.add(inv)
    await db_session.flush()
    pipeline = build_dossier_pipeline(inv, [])
    map_gl = next(s for s in pipeline if s.stage_id == "map_gl")
    assert map_gl.state == "pass"
    assert "5100" in map_gl.detail

    inv = Invoice(org_id=1, vendor="Acme", status=InvoiceStatus.EXCEPTION)
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log("invoice_uploaded", inv.id),
        _log("parsing_failed", inv.id, reason="no_stored_path"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    extract = next(s for s in pipeline if s.stage_id == "extract")
    assert extract.state == "fail"
    assert extract.remediation
    assert next(s for s in pipeline if s.stage_id == "classify").blocked_reason


@pytest.mark.asyncio
async def test_pipeline_extract_ignores_stale_parsing_failed_after_success(
    db_session: AsyncSession,
) -> None:
    """Concurrent re-run can log parsing_failed after parse_completed; dossier should not lie."""
    inv = Invoice(
        org_id=1,
        vendor="Hilton Sydney",
        invoice_no="HIL-SYD-5572",
        document_type_code="DT-03",
        status=InvoiceStatus.EXCEPTION,
    )
    db_session.add(inv)
    await db_session.flush()

    t0 = datetime(2026, 6, 20, 5, 2, 7, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 20, 5, 2, 27, tzinfo=timezone.utc)
    logs = [
        AuditLog(
            event="parse_completed",
            invoice_id=inv.id,
            created_at=t0,
            detail={"confidence": "high"},
        ),
        AuditLog(
            event="parsing_failed",
            invoice_id=inv.id,
            created_at=t1,
            detail={"reason": "stored_file_missing"},
        ),
        AuditLog(
            event="document_classified",
            invoice_id=inv.id,
            created_at=t0,
            detail={"document_type_code": "DT-03"},
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    extract = next(s for s in pipeline if s.stage_id == "extract")
    assert extract.state == "pass"
    assert extract.exception_code is None
