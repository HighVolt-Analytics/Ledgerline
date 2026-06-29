"""Audit event order for the strict 5-step pre-extract pipeline."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.pipeline import process_invoice
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

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.91,
            perspective="purchase",
            vendor="Acme Pty Ltd",
            total="120.00",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
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

    storage_idx = events.index("storage_verified")
    ocr_idx = events.index("ocr_completed")
    quality_idx = events.index("image_quality_gate_passed")
    classify_idx = events.index("llm_classified")
    gate_idx = events.index("classification_gate_passed")
    parse_idx = events.index("parse_completed")

    assert storage_idx < ocr_idx < quality_idx < classify_idx < gate_idx < parse_idx
    assert inv.vendor == "Acme Pty Ltd"


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

    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)

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
    storage_idx = events.index("storage_verified")
    ocr_idx = events.index("ocr_completed")
    quality_idx = events.index("image_quality_gate_passed")
    classify_idx = events.index("llm_classified")
    gate_idx = events.index("classification_gate_failed")
    assert storage_idx < ocr_idx < quality_idx < classify_idx < gate_idx
