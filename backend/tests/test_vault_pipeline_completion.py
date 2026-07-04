"""Vault route terminal state: processed archive docs should not linger as needs_review."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED, ROUTE_VAULT
from app.services.invoice.pipeline import process_invoice
from app.tenant_ids import TESTING_TENANT_UUID
from tests.pipeline_test_helpers import patch_confidence_gate_pass


def _vendor_statement_ocr() -> OcrArtifact:
    text = (
        "Vendor statement of account summary from Atlassian Pty Ltd "
        "for period ending May 2026"
    )
    return OcrArtifact(
        success=True,
        sparse=False,
        text=text,
        text_length=len(text),
        di_model="prebuilt-layout",
    )


@pytest.mark.asyncio
async def test_vault_route_sets_auto_coded_on_success(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "vendor-statement.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="vault-completion-1",
        currency="AUD",
        email_attachment_name="vendor-statement.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = _vendor_statement_ocr()

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-13",
            confidence=0.92,
            reasoning="Vendor statement",
            perspective="supporting",
            seller=LlmParty(name="Atlassian Pty Ltd"),
        )

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-13",
            confidence=0.92,
            perspective="supporting",
            vendor="Atlassian Pty Ltd",
            seller=LlmParty(name="Atlassian Pty Ltd"),
        )

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    patch_confidence_gate_pass(monkeypatch, dt="DT-13", confidence=0.92)
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
    await db_session.refresh(inv)

    assert inv.status == InvoiceStatus.PROCESSED
    assert (inv.route_target or "").strip() == ROUTE_VAULT
    assert inv.evaluation_status == EVAL_AUTO_CODED

    events = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.invoice_id == inv.id)
        )
    ).scalars().all()
    assert "vault_stored" in events
