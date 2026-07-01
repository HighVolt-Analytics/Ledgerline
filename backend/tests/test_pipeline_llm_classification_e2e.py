"""Pipeline e2e: high-confidence LLM classification passes gate and extracts."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.pipeline import process_invoice
from app.tenant_ids import TESTING_TENANT_UUID
from tests.pipeline_test_helpers import patch_confidence_gate_pass


@pytest.mark.asyncio
async def test_pipeline_high_confidence_passes_gate_and_extracts(
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
        file_hash="e2e-hash-llm-mismatch",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr_text = "BANK STATEMENT — account summary only with sufficient OCR text length for quality gate"
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

    def _fake_llm(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.92,
            reasoning="Looks like a tax invoice",
            perspective="purchase",
            vendor="Acme Pty Ltd",
            total="120.00",
        )

    async def _fake_llm_async(*_args, **_kwargs) -> LlmDocumentResult:
        return _fake_llm()

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    patch_confidence_gate_pass(monkeypatch)
    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_llm_async,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_llm_async)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", _noop_sync)

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.llm_suggested_dt == "DT-03"
    assert inv.llm_confidence == pytest.approx(0.92, rel=1e-3)
    assert inv.vendor is not None
