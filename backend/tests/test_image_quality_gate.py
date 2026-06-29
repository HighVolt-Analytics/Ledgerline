"""Image quality gate (pre-classify) and per-field confidence gate (post-extract)."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.invoice_evaluation_service import EVAL_NEEDS_RESCAN, EVAL_NEEDS_REVIEW
from app.services.invoice_pipeline_phases import (
    evaluate_field_confidence_gate,
    evaluate_image_quality_gate,
)
from app.services.pipeline import process_invoice
from app.schemas.rule_book_config import AiClassificationConfig
from app.tenant_ids import TESTING_TENANT_UUID


def _good_ocr() -> OcrArtifact:
    text = "TAX INVOICE from Acme Pty Ltd ABN 12 345 678 901 invoice #INV-001 total $120.00 GST included"
    return OcrArtifact(
        success=True,
        sparse=False,
        text=text,
        text_length=len(text),
        di_model="prebuilt-layout",
    )


def test_image_quality_gate_rejects_sparse_ocr() -> None:
    ocr = OcrArtifact(
        success=True,
        sparse=True,
        text="blurry photo",
        text_length=12,
        di_model="prebuilt-layout",
    )
    result = evaluate_image_quality_gate(ocr, ai_cfg=AiClassificationConfig())
    assert not result.passed
    assert "OCR_SPARSE" in result.review_reasons


def test_image_quality_gate_rejects_short_text() -> None:
    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text="short",
        text_length=5,
        di_model="prebuilt-layout",
    )
    result = evaluate_image_quality_gate(ocr, ai_cfg=AiClassificationConfig())
    assert not result.passed
    assert "IMAGE_QUALITY_LOW" in result.review_reasons


def test_field_confidence_gate_flags_low_gst() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-03",
        confidence=0.9,
        perspective="purchase",
        vendor="Acme Pty Ltd",
        total="120.00",
        gst="10.00",
        field_confidence={"gst": 0.4, "total": 0.95, "vendor": 0.9},
    )
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
    )
    assert not result.passed
    assert result.low_confidence_fields.get("gst") == pytest.approx(0.4)
    assert "FIELD_CONFIDENCE_LOW" in result.review_reasons


@pytest.mark.asyncio
async def test_pipeline_image_quality_blocks_classify(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "skewed.jpg.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="quality-fail",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    bad_ocr = OcrArtifact(
        success=True,
        sparse=True,
        text="partial thumb",
        text_length=13,
        di_model="prebuilt-layout",
    )

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return bad_ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        raise AssertionError("classify must not run when image quality gate fails")

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

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.status == InvoiceStatus.EXCEPTION
    assert inv.evaluation_status == EVAL_NEEDS_RESCAN
    assert inv.llm_suggested_dt is None


@pytest.mark.asyncio
async def test_pipeline_field_confidence_sets_needs_review(
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
        file_hash="field-conf-low",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    ocr = _good_ocr()

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        yield path

    async def _fake_read(*_args, **_kwargs) -> OcrArtifact:
        return ocr

    async def _fake_classify(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.92,
            reasoning="Clear tax invoice",
            perspective="purchase",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.92,
            perspective="purchase",
            vendor="Acme Pty Ltd",
            total="120.00",
            gst="10.00",
            seller=LlmParty(name="Acme Pty Ltd"),
            field_confidence={"gst": 0.35, "total": 0.95, "vendor": 0.9},
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

    assert inv.vendor == "Acme Pty Ltd"
    assert inv.evaluation_status == EVAL_NEEDS_REVIEW
