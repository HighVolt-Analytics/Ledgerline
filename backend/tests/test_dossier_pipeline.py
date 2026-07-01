"""Unit tests for dossier pipeline builder."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier_pipeline_service import STAGE_IDS, build_dossier_pipeline, first_pipeline_failure
from app.tenant_ids import TESTING_TENANT_UUID


def _log(event: str, invoice_id: int, **detail: object) -> AuditLog:
    return AuditLog(
        event=event,
        invoice_id=invoice_id,
        created_at=datetime.now(timezone.utc),
        detail=dict(detail),
    )


@pytest.mark.asyncio
async def test_pipeline_always_twenty_stages(db_session: AsyncSession) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="Acme", status=InvoiceStatus.PENDING)
    db_session.add(inv)
    await db_session.flush()
    pipeline = build_dossier_pipeline(inv, [])
    assert len(pipeline) == 20
    assert [step.stage_id for step in pipeline] == list(STAGE_IDS)


@pytest.mark.asyncio
async def test_pipeline_processed_invoice_full_pass(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
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
        _log(
            "vendor_registration_cleared",
            inv.id,
            reason="vendor_in_master",
            vendor="Meridian Foods",
        ),
        _log("validation_passed", inv.id),
        _log("mapping_applied", inv.id, account_name="5100 Food inventory", rule_type="purchase_rule"),
        _log("invoice_processed", inv.id, route_target="purchases"),
    ]
    pipeline = build_dossier_pipeline(inv, logs, payment_status="awaiting", payment_detail="Awaiting payment")

    passed = [s for s in pipeline if s.state == "pass"]
    assert len(passed) >= 10
    assert pipeline[0].stage_id == "ingest" and pipeline[0].state == "pass"
    post = next(s for s in pipeline if s.stage_id == "post")
    assert post.state == "pending"
    assert "ledger" in post.detail.lower()
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert validate.state == "pass" and validate.checks
    assert first_pipeline_failure(pipeline) is None


@pytest.mark.asyncio
async def test_pipeline_duplicate_blocks_downstream(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        file_hash="x",
    )
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
        tenant_id=TESTING_TENANT_UUID,
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

    inv = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="Acme", status=InvoiceStatus.EXCEPTION)
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log("invoice_uploaded", inv.id),
        _log("parsing_failed", inv.id, reason="no_stored_path"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    storage = next(s for s in pipeline if s.stage_id == "storage")
    assert storage.state == "fail"
    assert storage.remediation
    assert next(s for s in pipeline if s.stage_id == "document_type").blocked_reason


@pytest.mark.asyncio
async def test_pipeline_classify_passes_after_human_resolve() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-11",
        document_type_confidence=0.95,
        llm_suggested_dt="DT-03",
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("parse_completed", 1, confidence=0.9),
        _log(
            "routing_review_required",
            1,
            gate="classification",
            review_reasons=["DT_MISMATCH"],
        ),
        _log("classification_resolved", 1, confirmed_dt="DT-11"),
        _log("document_classified", 1, confirmed_dt="DT-11", human_locked=True),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    gate = next(s for s in pipeline if s.stage_id == "confidence_gate")
    assert gate.state == "pass"
    assert gate.exception_code is None
    doc_type = next(s for s in pipeline if s.stage_id == "document_type")
    assert doc_type.state == "pass"


@pytest.mark.asyncio
async def test_pipeline_gate_passes_when_resolve_supersedes_stale_gate_fail() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-11",
        document_type_confidence=0.95,
        evaluation_status="awaiting_classification",
        llm_suggested_dt="DT-03",
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("parse_completed", 1, confidence=0.9),
        _log("classification_gate_failed", 1, review_reasons=["LOW_CONFIDENCE"]),
        _log(
            "routing_review_required",
            1,
            gate="classification",
            review_reasons=["LOW_CONFIDENCE"],
        ),
        _log("classification_resolved", 1, confirmed_dt="DT-11"),
        _log("document_classified", 1, confirmed_dt="DT-11", human_locked=True),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    gate = next(s for s in pipeline if s.stage_id == "confidence_gate")
    assert gate.state == "pass"
    assert "Human confirmed" in gate.detail


@pytest.mark.asyncio
async def test_pipeline_unclassified_blocks_downstream() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-24",
        document_type_confidence=0.44,
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("parse_completed", 1, confidence=0.9),
        _log("document_classified", 1, document_type_code="DT-24"),
        _log(
            "routing_review_required",
            1,
            gate="classification",
            no_classifier_match=True,
            reason="No classifier matched in rule book catalogue",
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    gate = next(s for s in pipeline if s.stage_id == "confidence_gate")
    assert gate.state == "fail"
    assert gate.exception_code == "DOCUMENT_UNCLASSIFIED"
    bundle = next(s for s in pipeline if s.stage_id == "bundle")
    assert bundle.state == "pending"
    assert bundle.blocked_reason
    assert first_pipeline_failure(pipeline) is not None
    assert first_pipeline_failure(pipeline).stage_id == "confidence_gate"


@pytest.mark.asyncio
async def test_pipeline_extract_ignores_stale_parsing_failed_after_success(
    db_session: AsyncSession,
) -> None:
    """Concurrent re-run can log parsing_failed after parse_completed; dossier should not lie."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
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


@pytest.mark.asyncio
async def test_pipeline_bundle_linkage_key_missing_exception() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-01",
    )
    logs = [
        _log(
            "routing_review_required",
            1,
            gate="playbook",
            playbook={
                "block_reason": "linkage",
                "linkage_key_missing": True,
                "missing_bundle_mandatory": ["DT-02", "DT-03"],
                "blocks_posting": True,
            },
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    bundle = next(s for s in pipeline if s.stage_id == "bundle")
    assert bundle.state == "fail"
    assert bundle.exception_code == "LINKAGE_KEY_MISSING"
    assert bundle.failure_reason
    assert "PO number" in (bundle.failure_reason or "")


@pytest.mark.asyncio
async def test_pipeline_bundle_incomplete_with_labels() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-01",
        po_reference="PO-12345",
    )
    logs = [
        _log(
            "playbook_evaluated",
            1,
            block_reason="bundle",
            missing_bundle_mandatory=["DT-02"],
            missing_bundle_mandatory_labels={"DT-02": "PO copy"},
            blocks_posting=True,
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    bundle = next(s for s in pipeline if s.stage_id == "bundle")
    assert bundle.state == "fail"
    assert bundle.exception_code == "BUNDLE_INCOMPLETE"
    assert "PO copy" in (bundle.failure_reason or "")


@pytest.mark.asyncio
async def test_pipeline_vendor_hold_cleared_from_audit(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Known Vendor Pty Ltd",
        status=InvoiceStatus.PROCESSED,
        evaluation_status="auto_coded",
    )
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log(
            "vendor_registration_cleared",
            inv.id,
            reason="vendor_in_master",
            vendor="Known Vendor Pty Ltd",
        ),
        _log("validation_passed", inv.id),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    vendor_hold = next(s for s in pipeline if s.stage_id == "vendor_hold")
    assert vendor_hold.state == "pass"
    assert "vendor_in_master" in vendor_hold.detail or "registered vendor" in vendor_hold.detail.lower()


@pytest.mark.asyncio
async def test_pipeline_vendor_hold_waived_from_audit(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Any Vendor",
        status=InvoiceStatus.PROCESSED,
        purchase_document_type="grn",
    )
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log(
            "vendor_registration_waived",
            inv.id,
            reason="supporting_purchase_document",
            purchase_document_type="grn",
        ),
        _log("validation_passed", inv.id),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    vendor_hold = next(s for s in pipeline if s.stage_id == "vendor_hold")
    assert vendor_hold.state == "waived"
    assert "supporting" in vendor_hold.detail.lower() or "grn" in vendor_hold.detail.lower()


@pytest.mark.asyncio
async def test_pipeline_validate_notes_human_bypass(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        validation_results='[{"rule":"VR03","passed":true,"message":"ok"}]',
    )
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log("validation_bypassed_after_human_approval", inv.id),
        _log("validation_passed", inv.id),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert validate.state == "pass"
    assert "human approval bypassed" in validate.detail.lower()


@pytest.mark.asyncio
async def test_pipeline_validate_waived_when_bypass_with_failed_checks(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Everest Furnishings",
        status=InvoiceStatus.PROCESSED,
        po_reference="PO-2026-0612",
        validation_results=(
            '[{"rule":"VR14","passed":false,"message":"Currency mismatch","skipped":false},'
            '{"rule":"VR15","passed":false,"message":"Qty over-billing","skipped":false}]'
        ),
    )
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log("validation_bypassed_after_human_approval", inv.id),
        _log("validation_passed", inv.id),
        _log("three_way_match_evaluated", inv.id, status="variance"),
        _log("mapping_applied", inv.id, account_name="5100"),
        _log("invoice_processed", inv.id),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert validate.state == "waived"
    assert validate.checks
    match = next(s for s in pipeline if s.stage_id == "match")
    assert match.state == "fail"
    journal = next(s for s in pipeline if s.stage_id == "journal")
    assert journal.state == "pending"
    assert journal.blocked_reason and journal.blocked_reason.startswith("Blocked —")


@pytest.mark.asyncio
async def test_pipeline_vr12_legacy_skip_shows_fail(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Supplier",
        status=InvoiceStatus.EXCEPTION,
        validation_results=(
            '[{"rule":"VR12","passed":true,"skipped":true,'
            '"message":"Vendor master check skipped — no masters configured"}]'
        ),
    )
    db_session.add(inv)
    await db_session.flush()
    pipeline = build_dossier_pipeline(inv, [])
    validate = next(s for s in pipeline if s.stage_id == "validate")
    vr12 = next(c for c in validate.checks if c.rule_ref == "VR12")
    assert vr12.state == "fail"
    assert validate.state == "fail"


@pytest.mark.asyncio
async def test_pipeline_validate_fail_blocks_processed_downstream(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Co",
        status=InvoiceStatus.EXCEPTION,
        validation_results='[{"rule":"VR12","passed":false,"message":"Vendor not found","skipped":false}]',
    )
    db_session.add(inv)
    await db_session.flush()
    logs = [
        _log("validation_failed", inv.id, reason="VR12"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert validate.state == "fail"
    map_gl = next(s for s in pipeline if s.stage_id == "map_gl")
    assert map_gl.state == "pending"
    assert map_gl.blocked_reason
