"""Human-confirmed DT bypasses LLM review gate on reprocess."""

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
from app.services.audit_service import log_event
from app.services.document_type_playbook_service import PlaybookGateResult
from app.services.pipeline import process_invoice
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_reprocess_honors_human_confirmed_dt(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "permit.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="human-lock-hash",
        currency="AUD",
        document_type_code="DT-11",
        document_type_confidence=0.95,
    )
    db_session.add(inv)
    await db_session.flush()

    await log_event(
        db_session,
        "classification_resolved",
        invoice_id=inv.id,
        detail={"confirmed_dt": "DT-11"},
    )
    await db_session.flush()

    ocr_text = "CARGO CLEARANCE PERMIT issued for vessel MV Example with sufficient readable OCR text"
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
        raise AssertionError("classify must not run when human locked DT")

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-11",
            confidence=0.95,
            reasoning="Human locked",
            perspective="purchase",
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

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.document_type_code == "DT-11"
    events = (
        await db_session.execute(
            select(AuditLog.event, AuditLog.detail).where(AuditLog.invoice_id == inv.id)
        )
    ).all()
    classification_reviews = [
        detail
        for event, detail in events
        if event == "routing_review_required"
        and isinstance(detail, dict)
        and detail.get("gate") == "classification"
    ]
    assert classification_reviews == []
