"""Audit tab pipeline stages branch on vision understand vs legacy OCR."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.pipeline_stages import build_pipeline_stages
from app.tenant_ids import TESTING_TENANT_UUID

_BASE = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


def _log(event: str, *, minutes: int, detail: dict | None = None) -> AuditLog:
    return AuditLog(
        tenant_id=TESTING_TENANT_UUID,
        event=event,
        detail=detail or {},
        created_at=_BASE + timedelta(minutes=minutes),
    )


def test_audit_stages_understood_flow_hides_legacy_ocr() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
    )
    logs = [
        _log("invoice_uploaded", minutes=0),
        _log("storage_verified", minutes=1, detail={"document_ai_provider": "gemini_vision"}),
        _log("file_validity_passed", minutes=2),
        # Stale legacy path from an earlier reprocess
        _log("vision_understand_failed", minutes=3, detail={"confidence": 0.2}),
        _log("image_quality_passed", minutes=4, detail={"severity": "pass"}),
        _log("layout_readiness_evaluated", minutes=5, detail={"ocr_mode": "standard_di"}),
        _log("ocr_completed", minutes=6, detail={"confidence": "high"}),
        # Latest understand → vision path
        _log("vision_understand_passed", minutes=10, detail={"confidence": 0.91}),
        _log(
            "vision_header_extracted",
            minutes=11,
            detail={"document_heading": "PACKING LIST"},
        ),
        _log("vision_path_pending", minutes=12),
    ]

    stages = {s.stage: s for s in build_pipeline_stages(inv, logs)}
    assert "Vision understand" in stages
    assert "Can understand" in stages["Vision understand"].detail
    assert "Vision header" in stages
    assert "PACKING LIST" in stages["Vision header"].detail
    assert stages["Vision header"].state == "done"
    assert "Image quality" not in stages
    assert "Layout readiness" not in stages
    assert "OCR" not in stages
    assert stages["Parsed"].state == "done"
    assert "bundled" in stages["Parsed"].detail.lower() or "vault" in stages["Parsed"].detail.lower()
    assert stages["Validated"].state == "skipped"
    assert stages["Mapped"].state == "skipped"
    assert stages["Approved"].state == "skipped"
    assert stages["Posted"].state == "skipped"


def test_audit_stages_not_understood_flow_hides_vision_header() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    logs = [
        _log("invoice_uploaded", minutes=0),
        _log("storage_verified", minutes=1),
        _log("file_validity_passed", minutes=2),
        # Stale vision path from an earlier reprocess
        _log("vision_understand_passed", minutes=3, detail={"confidence": 0.9}),
        _log(
            "vision_header_extracted",
            minutes=4,
            detail={"document_heading": "TAX INVOICE"},
        ),
        _log("vision_path_pending", minutes=5),
        # Latest understand → legacy OCR
        _log("vision_understand_failed", minutes=10, detail={"confidence": 0.3}),
        _log("image_quality_passed", minutes=11, detail={"severity": "pass"}),
        _log("layout_readiness_evaluated", minutes=12, detail={"ocr_mode": "standard_di"}),
        _log("ocr_completed", minutes=13, detail={"confidence": "medium"}),
    ]

    stages = {s.stage: s for s in build_pipeline_stages(inv, logs)}
    assert "Vision understand" in stages
    assert "Cannot understand" in stages["Vision understand"].detail
    assert "Vision header" not in stages
    assert "Image quality" in stages
    assert "Layout readiness" in stages
    assert "OCR" in stages


def test_audit_stages_understood_shows_bundle_and_vault() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        extracted_fields={
            "vision_bundle_kind": "invoice_no",
            "vision_bundle_key": "INV-1",
        },
    )
    logs = [
        _log("invoice_uploaded", minutes=0),
        _log("storage_verified", minutes=1),
        _log("file_validity_passed", minutes=2),
        _log("vision_understand_passed", minutes=3, detail={"confidence": 0.9}),
        _log(
            "vision_header_extracted",
            minutes=4,
            detail={"document_heading": "TAX INVOICE"},
        ),
        _log(
            "vision_bundle_linked",
            minutes=5,
            detail={"vision_bundle_kind": "invoice_no", "vision_bundle_key": "INV-1"},
        ),
        _log(
            "blob_relocated",
            minutes=6,
            detail={"book": "Tax Invoice", "reason": "vision_header_vault_already_aligned"},
        ),
        _log("vision_path_pending", minutes=7),
    ]
    stages = {s.stage: s for s in build_pipeline_stages(inv, logs)}
    assert stages["Bundle"].state == "done"
    assert "INV-1" in stages["Bundle"].detail
    assert stages["Vault"].state == "done"
    assert "Tax Invoice" in stages["Vault"].detail
    assert stages["Validated"].state == "skipped"
    assert "understood path" in stages["Validated"].detail.lower()


def test_resolve_pipeline_active_path_understood() -> None:
    from app.services.invoice.pipeline_stages import (
        filter_pipeline_stages_for_path,
        resolve_pipeline_active_path,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
    )
    logs = [
        _log("storage_verified", minutes=1),
        _log("vision_understand_passed", minutes=2, detail={"confidence": 0.9}),
        _log("vision_header_extracted", minutes=3, detail={"document_heading": "TAX INVOICE"}),
        _log("vision_path_pending", minutes=4),
    ]
    assert resolve_pipeline_active_path(logs) == "understood"
    steps = build_pipeline_stages(inv, logs)
    understood = filter_pipeline_stages_for_path(steps, "understood")
    names = [s.stage for s in understood]
    assert "Vision header" in names
    assert "Validated" not in names
    assert "OCR" not in names


def test_resolve_pipeline_active_path_not_understood() -> None:
    from app.services.invoice.pipeline_stages import (
        filter_pipeline_stages_for_path,
        resolve_pipeline_active_path,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    logs = [
        _log("storage_verified", minutes=1),
        _log("vision_understand_failed", minutes=2, detail={"confidence": 0.2}),
        _log("image_quality_passed", minutes=3, detail={"severity": "pass"}),
        _log("ocr_completed", minutes=4, detail={"confidence": "high"}),
    ]
    assert resolve_pipeline_active_path(logs) == "not_understood"
    steps = build_pipeline_stages(inv, logs)
    legacy = filter_pipeline_stages_for_path(steps, "not_understood")
    names = [s.stage for s in legacy]
    assert "OCR" in names
    assert "Vision header" not in names
    assert "Bundle" not in names
