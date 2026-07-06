"""Unit tests for dossier pipeline builder."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.dossier_pipeline_service import (
    STAGE_IDS,
    build_dossier_pipeline,
    classification_review_pending,
    first_pipeline_failure,
)
from app.services.dossier.dossier_service import _confidence_pct, build_dossier_summary
from app.tenant_ids import TESTING_TENANT_UUID


def _log(event: str, invoice_id: int, **detail: object) -> AuditLog:
    return AuditLog(
        event=event,
        invoice_id=invoice_id,
        created_at=datetime.now(timezone.utc),
        detail=dict(detail),
    )


def _log_at(event: str, invoice_id: int, offset_sec: int = 0, **detail: object) -> AuditLog:
    return AuditLog(
        event=event,
        invoice_id=invoice_id,
        created_at=datetime.now(timezone.utc) + timedelta(seconds=offset_sec),
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
async def test_pipeline_duplicate_in_progress_does_not_block_canonical_row() -> None:
    """Concurrent re-submit logs duplicate_in_progress on the original — pipeline must not stall."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        file_hash="canonical-hash",
    )
    logs = [
        _log_at("invoice_uploaded", 1, 0),
        _log_at("duplicate_in_progress", 1, 1, filename="same.pdf"),
        _log_at("storage_verified", 1, 2),
        _log_at("ocr_completed", 1, 3),
        _log_at("parse_completed", 1, 4, confidence=0.9),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    duplicate = next(s for s in pipeline if s.stage_id == "duplicate")
    assert duplicate.state == "pass"
    storage = next(s for s in pipeline if s.stage_id == "storage")
    assert storage.state == "pass"
    assert storage.blocked_reason is None
    assert first_pipeline_failure(pipeline) is None or first_pipeline_failure(pipeline).stage_id != "duplicate"


@pytest.mark.asyncio
async def test_pipeline_requeued_passes_storage_when_file_on_record() -> None:
    """After requeue, storage_verified is outside the cycle but the PDF is still on record."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        file_hash="stored-hash",
        raw_file_path="blob://invoices/tenant/acme/inv-1.pdf",
    )
    logs = [
        _log_id("invoice_requeued", 1, 1),
        _log_id("ocr_completed", 1, 2, text_length=1200),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    storage = next(s for s in pipeline if s.stage_id == "storage")
    ocr = next(s for s in pipeline if s.stage_id == "ocr")
    assert storage.state == "pass"
    assert storage.blocked_reason is None
    assert ocr.state == "pass"


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
async def test_gate_pass_supersedes_stale_classification_routing_review() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-03",
        document_type_confidence=0.92,
        llm_suggested_dt="DT-03",
        llm_confidence=0.92,
    )
    logs = [
        _log_at("invoice_uploaded", 1, 0),
        _log_at("llm_classified", 1, 1, llm_suggested_dt="DT-03", llm_confidence=0.51),
        _log_at("classification_gate_failed", 1, 2, review_reasons=["LLM_LOW_CONF"]),
        _log_at(
            "routing_review_required",
            1,
            3,
            gate="classification",
            review_reasons=["LLM_LOW_CONF"],
        ),
        _log_at("llm_classified", 1, 10, llm_suggested_dt="DT-03", llm_confidence=0.92),
        _log_at(
            "classification_gate_passed",
            1,
            11,
            llm_suggested_dt="DT-03",
            llm_confidence=0.92,
            compare_passed=True,
        ),
        _log_at("document_classified", 1, 12, confirmed_dt="DT-03"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    gate = next(s for s in pipeline if s.stage_id == "confidence_gate")
    assert gate.state == "pass"
    assert gate.exception_code is None
    assert classification_review_pending(logs) is False
    doc_type = next(s for s in pipeline if s.stage_id == "document_type")
    assert doc_type.state == "pass"


@pytest.mark.asyncio
async def test_ocr_failure_routing_superseded_by_successful_reclassify() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        document_type_confidence=0.95,
        llm_suggested_dt="DT-01",
        llm_confidence=0.95,
    )
    logs = [
        _log_at("invoice_uploaded", 1, 0),
        _log_at("parsing_failed", 1, 1, reason="ocr_failed"),
        _log_at(
            "routing_review_required",
            1,
            2,
            gate="classification",
            review_reasons=["PROVIDER_UNAVAILABLE"],
            provider_unavailable=True,
        ),
        _log_at("parse_completed", 1, 10, confidence=0.9),
        _log_at("llm_classified", 1, 11, llm_suggested_dt="DT-01", llm_confidence=0.95),
        _log_at(
            "classification_gate_passed",
            1,
            12,
            llm_suggested_dt="DT-01",
            llm_confidence=0.95,
            compare_passed=True,
        ),
        _log_at("document_classified", 1, 13, confirmed_dt="DT-01"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    gate = next(s for s in pipeline if s.stage_id == "confidence_gate")
    assert gate.state == "pass"
    assert classification_review_pending(logs) is False
    assert first_pipeline_failure(pipeline) is None or first_pipeline_failure(pipeline).stage_id != "confidence_gate"


@pytest.mark.asyncio
async def test_gate_failure_shows_human_readable_review_reasons() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        llm_suggested_dt="DT-03",
        llm_confidence=0.51,
        evaluation_status="awaiting_classification",
    )
    logs = [
        _log_at("llm_classified", 1, 0, llm_suggested_dt="DT-03", llm_confidence=0.51),
        _log_at("classification_gate_failed", 1, 1, review_reasons=["LLM_LOW_CONF"]),
        _log_at(
            "routing_review_required",
            1,
            2,
            gate="classification",
            review_reasons=["LLM_LOW_CONF"],
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    gate = next(s for s in pipeline if s.stage_id == "confidence_gate")
    assert gate.state == "fail"
    assert "LLM confidence below auto-route threshold" in (gate.failure_reason or "")


def test_confidence_display_does_not_round_up_pending() -> None:
    assert _confidence_pct(0.846, floor=True) == 84
    assert _confidence_pct(0.846) == 85


@pytest.mark.asyncio
async def test_summary_label_shows_review_when_pending_with_suggestion(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        llm_suggested_dt="DT-03",
        llm_confidence=0.846,
        evaluation_status="awaiting_classification",
        file_hash="dossier-pending-label",
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log_at("llm_classified", inv.id, 0, llm_suggested_dt="DT-03", llm_confidence=0.846),
        _log_at("classification_gate_failed", inv.id, 1, review_reasons=["LLM_LOW_CONF"]),
        _log_at(
            "routing_review_required",
            inv.id,
            2,
            gate="classification",
            review_reasons=["LLM_LOW_CONF"],
        ),
    ]
    summary = await build_dossier_summary(db_session, inv, logs, compact=True)
    assert "needs review" in summary.classification_label.lower()
    assert summary.classification_confidence == 84
    assert summary.document_type_code == "DT-03"


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
    assert "PO reference" in (bundle.failure_reason or "")


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


@pytest.mark.asyncio
async def test_compact_pipeline_keeps_failure_fields_on_failed_step(
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
    pipeline = build_dossier_pipeline(inv, logs, compact=True)
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert validate.state == "fail"
    assert validate.failure_reason
    assert validate.remediation
    assert validate.checks == []
    assert validate.evidence == []
    ingest = next(s for s in pipeline if s.stage_id == "ingest")
    assert ingest.failure_reason is None
    assert ingest.remediation is None


def _log_id(event: str, invoice_id: int, log_id: int, **detail: object) -> AuditLog:
    return AuditLog(
        id=log_id,
        event=event,
        invoice_id=invoice_id,
        created_at=datetime.now(timezone.utc) + timedelta(seconds=log_id),
        detail=dict(detail),
    )


@pytest.mark.asyncio
async def test_pipeline_llm_classify_inferred_when_gate_passed_without_llm_log() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Spectra",
        status=InvoiceStatus.PARSING,
        document_type_code="DT-01",
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("parse_completed", 1),
        _log("classification_gate_passed", 1, confirmed_dt="DT-01"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    llm = next(s for s in pipeline if s.stage_id == "llm_classify")
    assert llm.state == "pass"
    assert "skipped" in llm.detail or "DT-01" in llm.detail


@pytest.mark.asyncio
async def test_pipeline_map_gl_pending_blocks_journal_and_post() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Spectra",
        status=InvoiceStatus.MAPPING,
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("parse_completed", 1),
        _log("validation_passed", 1),
        _log("invoice_processed", 1),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    map_gl = next(s for s in pipeline if s.stage_id == "map_gl")
    journal = next(s for s in pipeline if s.stage_id == "journal")
    post = next(s for s in pipeline if s.stage_id == "post")
    assert map_gl.state == "pending"
    assert map_gl.detail == "Awaiting mapping"
    assert journal.state == "pending"
    assert post.state == "pending"


@pytest.mark.asyncio
async def test_pipeline_cycle_reset_ignores_stale_processed_logs() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Spectra",
        status=InvoiceStatus.MAPPING,
    )
    logs = [
        _log_id("invoice_uploaded", 1, 1),
        _log_id("invoice_processed", 1, 2),
        _log_id("mapping_applied", 1, 3, account_name="5100"),
        _log_id("invoice_requeued", 1, 4),
        _log_id("validation_passed", 1, 5),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    map_gl = next(s for s in pipeline if s.stage_id == "map_gl")
    journal = next(s for s in pipeline if s.stage_id == "journal")
    assert map_gl.state == "pending"
    assert journal.state == "pending"


@pytest.mark.asyncio
async def test_pipeline_image_quality_routing_review_fails_quality_stage() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Spectra",
        status=InvoiceStatus.EXCEPTION,
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log(
            "routing_review_required",
            1,
            gate="image_quality",
            review_reasons=["OCR_SPARSE"],
            sparse=True,
            text_length=12,
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    quality = next(s for s in pipeline if s.stage_id == "quality")
    assert quality.state == "fail"
    assert quality.exception_code == "IMAGE_QUALITY"
    assert first_pipeline_failure(pipeline) is not None


@pytest.mark.asyncio
async def test_pipeline_approve_pending_does_not_downgrade_map_gl_pass() -> None:
    """Team expense approval runs after mapping — map_gl must stay pass."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        account_name="5100 Food inventory",
        account_code="5100",
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("parse_completed", 1),
        _log("validation_passed", 1),
        _log("mapping_applied", 1, account_name="5100 Food inventory"),
        _log("approval_requested", 1, reason="Over threshold"),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    approve = next(s for s in pipeline if s.stage_id == "approve")
    map_gl = next(s for s in pipeline if s.stage_id == "map_gl")
    journal = next(s for s in pipeline if s.stage_id == "journal")
    assert approve.state == "pending"
    assert map_gl.state == "pass"
    assert map_gl.blocked_reason is None
    assert journal.state == "pending"
    assert journal.blocked_reason and journal.blocked_reason.startswith("Blocked —")


@pytest.mark.asyncio
async def test_pipeline_vendor_cleared_passes_despite_stale_eval_status() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_vendor",
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("vendor_registration_hold", 1),
        _log("vendor_registration_cleared", 1, reason="vendor_in_master"),
        _log("validation_passed", 1),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    vendor_hold = next(s for s in pipeline if s.stage_id == "vendor_hold")
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert vendor_hold.state == "pass"
    assert validate.state == "pass"
    assert validate.blocked_reason is None


@pytest.mark.asyncio
async def test_pipeline_field_confidence_routing_fails_extract_not_validate() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PARSING,
        document_type_code="DT-01",
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("parse_completed", 1, confidence=0.9),
        _log(
            "routing_review_required",
            1,
            gate="field_confidence",
            review_reasons=["FIELD_CONFIDENCE_LOW"],
            low_confidence_fields=["gst"],
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    extract = next(s for s in pipeline if s.stage_id == "extract")
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert extract.state == "fail"
    assert extract.exception_code == "EXTRACTION_INCOMPLETE"
    assert validate.state == "pending"
    assert first_pipeline_failure(pipeline) is not None
    assert first_pipeline_failure(pipeline).stage_id == "extract"


@pytest.mark.asyncio
async def test_pipeline_vendor_drift_routing_fails_llm_classify_not_validate() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PARSING,
        llm_suggested_dt="DT-03",
    )
    logs = [
        _log("invoice_uploaded", 1),
        _log("llm_classified", 1, llm_suggested_dt="DT-08", llm_confidence=0.9),
        _log(
            "routing_review_required",
            1,
            gate="vendor_classification_drift",
            review_reasons=["VENDOR_CLASSIFICATION_DRIFT"],
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    llm = next(s for s in pipeline if s.stage_id == "llm_classify")
    validate = next(s for s in pipeline if s.stage_id == "validate")
    assert llm.state == "fail"
    assert llm.exception_code == "CLASSIFICATION_GATE"
    assert validate.state == "pending"
    assert first_pipeline_failure(pipeline) is not None
    assert first_pipeline_failure(pipeline).stage_id == "llm_classify"
