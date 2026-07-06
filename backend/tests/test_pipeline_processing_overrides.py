"""Pipeline honors per-invoice processing overrides."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.classification.document_type_playbook_service import PlaybookGateResult
from app.services.invoice.pipeline import process_invoice
from app.services.rule_book.validator import ValidationResult
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_image_quality_override_skips_sparse_gate(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "sparse.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="sparse-override-hash",
        currency="AUD",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        processing_overrides={"skip_steps": ["image_quality", "classification"]},
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = OcrArtifact(
        success=True,
        sparse=True,
        text="short",
        text_length=5,
        di_model="prebuilt-read",
    )

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        raise AssertionError("classify must not run when classification override active")

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-01",
            confidence=0.9,
            reasoning="test",
            perspective="purchase",
        )

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.shared.file_storage.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", _noop_sync)
    monkeypatch.setattr(
        "app.services.pipeline.apply_invoice_evaluation",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.pipeline.evaluate_playbook_gates",
        AsyncMock(
            return_value=PlaybookGateResult(
                missing_bundle_mandatory=(),
                missing_bundle_conditional_dt=(),
                conditional_advisories=(),
                missing_extraction_fields=(),
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.run_all_validations",
        AsyncMock(
            return_value=[ValidationResult("VR01", True, "ok", skipped=False)],
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.generate_entries",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "app.services.pipeline.reconcile_daily",
        AsyncMock(return_value=type("R", (), {"halted": False})()),
    )
    monkeypatch.setattr("app.services.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr(
        "app.services.pipeline.apply_document_type_approval_gate",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.pipeline.apply_vendor_hold_if_needed",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._resolve_header_mapping",
        lambda *_a, **_k: (
            type("M", (), {"account_code": "100", "account_name": "Suspense"})(),
            type("D", (), {"rule_type": "default", "match_reason": "test"})(),
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.requires_gl_mapping_review",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app.services.integration.publish_service.publish_invoice_to_ledger",
        AsyncMock(),
    )

    await process_invoice(db_session, inv)
    await db_session.flush()

    events = (
        await db_session.execute(
            select(AuditLog.event, AuditLog.detail).where(AuditLog.invoice_id == inv.id)
        )
    ).all()
    skipped = [
        detail
        for event, detail in events
        if event == "pipeline_step_skipped"
        and isinstance(detail, dict)
        and detail.get("step_id") == "image_quality"
    ]
    assert len(skipped) == 1
    quality_reviews = [
        detail
        for event, detail in events
        if event == "routing_review_required"
        and isinstance(detail, dict)
        and detail.get("gate") == "image_quality"
    ]
    assert quality_reviews == []


@pytest.mark.asyncio
async def test_validation_override_bypasses_failed_checks(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "valid.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="validation-override-hash",
        currency="AUD",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        route_target="Purchase Management",
        processing_overrides={"skip_steps": ["classification", "validation"]},
    )
    db_session.add(inv)
    await db_session.flush()

    ocr_text = "TAX INVOICE from Acme with enough readable OCR text for quality gate to pass easily"
    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text=ocr_text,
        text_length=len(ocr_text),
        di_model="prebuilt-read",
    )

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        raise AssertionError("classify must not run when classification override active")

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-01",
            confidence=0.9,
            reasoning="test",
            perspective="purchase",
        )

    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.shared.file_storage.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", AsyncMock())
    monkeypatch.setattr(
        "app.services.pipeline.apply_invoice_evaluation",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.pipeline.evaluate_playbook_gates",
        AsyncMock(
            return_value=PlaybookGateResult(
                missing_bundle_mandatory=(),
                missing_bundle_conditional_dt=(),
                conditional_advisories=(),
                missing_extraction_fields=(),
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.run_all_validations",
        AsyncMock(
            return_value=[
                ValidationResult("VR03", False, "Missing compulsory: vendor", skipped=False)
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.apply_document_type_approval_gate",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.pipeline.apply_vendor_hold_if_needed",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._resolve_header_mapping",
        lambda *_a, **_k: (
            type("M", (), {"account_code": "100", "account_name": "Suspense"})(),
            type("D", (), {"rule_type": "default", "match_reason": "test"})(),
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.requires_gl_mapping_review",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app.services.pipeline.generate_entries",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "app.services.pipeline.reconcile_daily",
        AsyncMock(return_value=type("R", (), {"halted": False})()),
    )
    monkeypatch.setattr("app.services.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr(
        "app.services.integration.publish_service.publish_invoice_to_ledger",
        AsyncMock(),
    )

    await process_invoice(db_session, inv)
    await db_session.flush()

    events = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.invoice_id == inv.id)
        )
    ).scalars().all()
    assert "validation_bypassed_processing_override" in events
    assert "pipeline_step_skipped" in events
    assert "validation_failed" not in events


@pytest.mark.asyncio
async def test_vendor_registration_override_skips_hold(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "vendor.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="vendor-override-hash",
        currency="AUD",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        route_target="Purchase Management",
        processing_overrides={"skip_steps": ["classification", "vendor_registration"]},
    )
    db_session.add(inv)
    await db_session.flush()

    ocr_text = "TAX INVOICE from Acme with enough readable OCR text for quality gate to pass easily"
    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text=ocr_text,
        text_length=len(ocr_text),
        di_model="prebuilt-read",
    )

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        raise AssertionError("classify must not run when classification override active")

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-01",
            confidence=0.9,
            reasoning="test",
            perspective="purchase",
        )

    async def _vendor_hold(*_args, **_kwargs) -> bool:
        raise AssertionError("vendor hold must not run when vendor_registration override active")

    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.shared.file_storage.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", AsyncMock())
    monkeypatch.setattr(
        "app.services.pipeline.apply_invoice_evaluation",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.pipeline.evaluate_playbook_gates",
        AsyncMock(
            return_value=PlaybookGateResult(
                missing_bundle_mandatory=(),
                missing_bundle_conditional_dt=(),
                conditional_advisories=(),
                missing_extraction_fields=(),
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.run_all_validations",
        AsyncMock(
            return_value=[ValidationResult("VR01", True, "ok", skipped=False)],
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.apply_document_type_approval_gate",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.pipeline.apply_vendor_hold_if_needed",
        _vendor_hold,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._resolve_header_mapping",
        lambda *_a, **_k: (
            type("M", (), {"account_code": "100", "account_name": "Suspense"})(),
            type("D", (), {"rule_type": "default", "match_reason": "test"})(),
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.requires_gl_mapping_review",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app.services.pipeline.generate_entries",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "app.services.pipeline.reconcile_daily",
        AsyncMock(return_value=type("R", (), {"halted": False})()),
    )
    monkeypatch.setattr("app.services.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr(
        "app.services.integration.publish_service.publish_invoice_to_ledger",
        AsyncMock(),
    )

    await process_invoice(db_session, inv)
    await db_session.flush()

    events = (
        await db_session.execute(
            select(AuditLog.event, AuditLog.detail).where(AuditLog.invoice_id == inv.id)
        )
    ).all()
    vendor_skipped = [
        detail
        for event, detail in events
        if event == "pipeline_step_skipped"
        and isinstance(detail, dict)
        and detail.get("step_id") == "vendor_registration"
    ]
    assert len(vendor_skipped) >= 1
    assert "vendor_registration_hold" not in [e for e, _ in events]
