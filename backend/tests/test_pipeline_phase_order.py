"""Audit event order for the strict pre-extract pipeline."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.invoice.pipeline import process_invoice
from tests.pipeline_test_helpers import patch_confidence_gate_pass, patch_pre_ocr_gates_pass
from app.tenant_ids import TESTING_TENANT_UUID


def _ocr() -> OcrArtifact:
    text = "TAX INVOICE from Acme Pty Ltd ABN 12 345 678 901 invoice #INV-001 total $120.00 GST included"
    return OcrArtifact(
        success=True,
        sparse=False,
        text=text,
        text_length=len(text),
        di_model="prebuilt-layout",
    )


def _assert_ordered(events: list[str], *names: str) -> None:
    indices = [events.index(name) for name in names]
    assert indices == sorted(indices), f"expected order {names}, got indices {indices} in {events}"


@pytest.mark.asyncio
async def test_pipeline_phase_audit_order_on_gate_pass(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="phase-order-pass",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = _ocr()

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.91,
            reasoning="Clear tax invoice",
            perspective="purchase",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _fake_extract(*_args, **_kwargs):
        from app.services.extraction.document_ai_provider import ExtractFieldsResult

        return ExtractFieldsResult(
            llm=LlmDocumentResult(
                suggested_dt="DT-03",
                confidence=0.91,
                perspective="purchase",
                vendor="Acme Pty Ltd",
                total="120.00",
                seller=LlmParty(name="Acme Pty Ltd"),
            ),
            ocr=ocr,
        )

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    patch_confidence_gate_pass(monkeypatch)
    patch_pre_ocr_gates_pass(monkeypatch)
    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.shared.file_storage.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.invoice.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.invoice.pipeline.sync_invoice_blob_path", _noop_sync)

    await process_invoice(db_session, inv)
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.invoice_id == inv.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
    ).scalars().all()
    events = [row.event for row in rows]

    _assert_ordered(
        events,
        "storage_verified",
        "file_validity_passed",
        "vision_understand_failed",
        "image_quality_passed",
        "layout_readiness_evaluated",
        "ocr_completed",
        "ocr_quality_confirm_passed",
        "llm_classified",
        "classification_gate_passed",
        "parse_completed",
    )
    assert inv.vendor and "Acme" in inv.vendor
    assert "ocr_quality_confirm_passed" in events or "image_quality_gate_passed" in events


@pytest.mark.asyncio
async def test_pipeline_phase_audit_order_on_gate_fail(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="phase-order-fail",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = _ocr()

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.55,
            reasoning="Uncertain",
            perspective="purchase",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        raise AssertionError("extract must not run when gate fails")

    patch_pre_ocr_gates_pass(monkeypatch)
    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.shared.file_storage.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.invoice.pipeline.extract_fields", _fake_extract)

    await process_invoice(db_session, inv)
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.invoice_id == inv.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
    ).scalars().all()
    events = [row.event for row in rows]

    assert "classification_gate_failed" in events
    assert "parse_completed" not in events
    _assert_ordered(
        events,
        "storage_verified",
        "file_validity_passed",
        "vision_understand_failed",
        "ocr_completed",
        "ocr_quality_confirm_passed",
        "llm_classified",
        "classification_gate_failed",
    )


@pytest.mark.asyncio
async def test_pipeline_holds_when_vision_can_understand(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from app.models.line_item import LineItem
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult
    from app.services.invoice.vision_understand_gate import VisionUnderstandResult

    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="phase-order-vision-hold",
        currency="AUD",
        # Stale not-understood leftovers (as after a failed-then-retry reprocess).
        document_type_code="DT-04",
        document_type_confidence=0.95,
        llm_suggested_dt="DT-04",
        llm_confidence=0.95,
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        extracted_fields={
            "field_confidence": {"total": 0.9, "line_items": 0.94},
            "subtotal": "100.00",
            "canonical_document_type": "Tax Invoice",
        },
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Stale fare line",
            amount=Decimal("79434.00"),
        )
    )
    await db_session.flush()

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _can_understand(*_args, **_kwargs) -> VisionUnderstandResult:
        return VisionUnderstandResult(
            can_understand=True,
            confidence=0.92,
            reason="clear_readable_invoice",
            provider="gemini_vision",
            page_count=1,
        )

    async def _header(*_args, **_kwargs) -> VisionHeaderExtractResult:
        return VisionHeaderExtractResult(
            success=True,
            document_heading="TAX INVOICE",
            canonical_document_type="Tax Invoice",
            counterparty_name="Acme Pty Ltd",
            perspective="purchase",
            invoice_no="INV-100",
            po_reference="PO-55",
            so_reference="",
            other_reference="",
            confidence=0.88,
            reason="clear header",
            provider="gemini_vision",
            page_count=1,
        )

    async def _fake_read(*_args, **_kwargs):
        raise AssertionError("legacy OCR must not run when vision can understand")

    async def _noop_siblings(*_args, **_kwargs):
        return None

    sync_calls: list[int] = []

    async def _fake_sync(session, invoice, *, parsed_vendor=None):
        sync_calls.append(invoice.id)
        return False

    patch_pre_ocr_gates_pass(monkeypatch)
    monkeypatch.setattr(
        "app.services.invoice.vision_understand_gate.evaluate_vision_understand",
        _can_understand,
    )
    monkeypatch.setattr(
        "app.services.invoice.vision_header_extract.evaluate_vision_header_extract",
        _header,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._maybe_reprocess_held_commercial_siblings",
        _noop_siblings,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline.sync_vision_header_vault_path",
        _fake_sync,
    )
    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.shared.file_storage.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )

    await process_invoice(db_session, inv)
    await db_session.flush()
    await db_session.refresh(inv)

    rows = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.invoice_id == inv.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
    ).scalars().all()
    events = [row.event for row in rows]

    assert inv.status == InvoiceStatus.EXCEPTION
    assert inv.document_heading == "TAX INVOICE"
    assert (inv.extracted_fields or {}).get("canonical_document_type") == "Tax Invoice"
    assert inv.invoice_no == "INV-100"
    assert inv.po_reference == "PO-55"
    assert inv.vendor == "Acme Pty Ltd"
    assert (inv.extracted_fields or {}).get("vision_bundle_kind") == "invoice_no"
    assert (inv.extracted_fields or {}).get("vision_bundle_key") == "INV-100"
    # Path-consistent: no not-understood leftovers mixed with vision header.
    assert inv.document_type_code is None
    assert inv.subtotal is None
    assert inv.gst is None
    assert "field_confidence" not in (inv.extracted_fields or {})
    assert "subtotal" not in (inv.extracted_fields or {})
    line_count = (
        await db_session.execute(
            select(LineItem).where(LineItem.invoice_id == inv.id)
        )
    ).scalars().all()
    assert line_count == []
    assert sync_calls == [inv.id]
    assert "vision_understand_passed" in events
    assert "vision_header_extracted" in events
    assert "vision_path_stale_extract_cleared" in events
    assert "vision_bundle_linked" in events
    assert "vision_path_pending" in events
    assert "image_quality_passed" not in events
    assert "ocr_completed" not in events
    _assert_ordered(
        events,
        "storage_verified",
        "file_validity_passed",
        "vision_understand_passed",
        "vision_header_extracted",
        "vision_path_stale_extract_cleared",
        "vision_bundle_linked",
        "vision_path_pending",
    )
