"""Per-vendor template learning and classification drift alerts."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import AiClassificationConfig
from app.services.classification_drift_service import (
    evaluate_vendor_classification_drift,
    vendor_classification_baseline,
)
from app.services.classification_learning_service import (
    few_shot_examples_for_tenant,
    record_learning_event,
    resolve_vendor_learning_key,
)
from app.services.invoice_evaluation_service import EVAL_NEEDS_REVIEW
from app.services.pipeline import process_invoice
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


def test_resolve_vendor_learning_key_prefers_slug() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        storage_vendor_slug="acme-pty-ltd",
        vendor="Other Name",
    )
    assert resolve_vendor_learning_key(inv) == "acme-pty-ltd"


def test_evaluate_vendor_drift_detects_drop() -> None:
    cfg = AiClassificationConfig(vendor_drift_min_samples=3, vendor_drift_confidence_drop=0.15)
    result = evaluate_vendor_classification_drift(
        vendor_key="acme-pty-ltd",
        current_confidence=0.62,
        baseline_mean=0.88,
        sample_count=8,
        ai_cfg=cfg,
    )
    assert result.detected is True
    assert "VENDOR_CLASSIFICATION_DRIFT" in result.review_reasons


def test_evaluate_vendor_drift_ignored_with_few_samples() -> None:
    cfg = AiClassificationConfig(vendor_drift_min_samples=5)
    result = evaluate_vendor_classification_drift(
        vendor_key="acme-pty-ltd",
        current_confidence=0.50,
        baseline_mean=0.90,
        sample_count=2,
        ai_cfg=cfg,
    )
    assert result.detected is False


@pytest.mark.asyncio
async def test_few_shot_examples_prefer_vendor_templates(db_session: AsyncSession) -> None:
    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=1,
        file_hash="tenant-wide",
        human_confirmed_dt="DT-16",
        document_heading="GENERIC STATEMENT",
        text_excerpt="Account statement summary",
    )
    await record_learning_event(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=2,
        file_hash="acme-v1",
        human_confirmed_dt="DT-03",
        vendor_key="acme-pty-ltd",
        document_heading="TAX INVOICE",
        text_excerpt="Acme Pty Ltd tax invoice layout v2",
    )
    await db_session.flush()

    examples = await few_shot_examples_for_tenant(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        limit=2,
        vendor_key="acme-pty-ltd",
        vendor_limit=2,
    )
    assert len(examples) == 2
    assert examples[0]["human_confirmed_dt"] == "DT-03"
    assert examples[0]["vendor_key"] == "acme-pty-ltd"


@pytest.mark.asyncio
async def test_vendor_classification_baseline(db_session: AsyncSession) -> None:
    for idx, conf in enumerate((0.9, 0.88, 0.91, 0.89), start=1):
        db_session.add(
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                status=InvoiceStatus.PROCESSED,
                storage_vendor_slug="acme-pty-ltd",
                llm_confidence=conf,
                currency="AUD",
            )
        )
    await db_session.flush()

    mean, count = await vendor_classification_baseline(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        vendor_key="acme-pty-ltd",
    )
    assert count == 4
    assert mean == pytest.approx(0.895, rel=1e-3)


@pytest.mark.asyncio
async def test_pipeline_vendor_drift_flags_needs_review(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for conf in (0.98, 0.99, 0.97, 0.98, 0.99):
        db_session.add(
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                status=InvoiceStatus.PROCESSED,
                storage_vendor_slug="acme-pty-ltd",
                llm_confidence=conf,
                currency="AUD",
            )
        )
    await db_session.flush()

    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=str(pdf_path),
        file_hash="drift-low-conf",
        currency="AUD",
        storage_vendor_slug="acme-pty-ltd",
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
            confidence=0.88,
            reasoning="Layout changed but still invoice-like",
            perspective="purchase",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        return LlmDocumentResult(
            suggested_dt="DT-03",
            confidence=0.88,
            perspective="purchase",
            vendor="Acme Pty Ltd",
            total="120.00",
            seller=LlmParty(name="Acme Pty Ltd"),
        )

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    from app.services.tenant_org_context import ai_classification_from_config as _real_ai_cfg

    def _ai_cfg_with_drift_threshold(config):
        cfg = _real_ai_cfg(config)
        return cfg.model_copy(update={"vendor_drift_confidence_drop": 0.08})

    monkeypatch.setattr("app.services.pipeline.ai_classification_from_config", _ai_cfg_with_drift_threshold)
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

    assert inv.evaluation_status in {EVAL_NEEDS_REVIEW, "awaiting_classification"}
    assert inv.llm_confidence == pytest.approx(0.88, rel=1e-3)
