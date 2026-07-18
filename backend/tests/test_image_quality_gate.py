"""Pre-OCR image quality detectors and post-OCR quality confirm."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import AiClassificationConfig
from app.services.invoice.image_quality_gate import evaluate_pre_ocr_image_quality
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import EVAL_NEEDS_RESCAN
from app.services.invoice.invoice_pipeline_phases import (
    evaluate_field_confidence_gate,
    evaluate_image_quality_gate,
    evaluate_ocr_quality_confirm,
)
from app.services.invoice.layout_readiness import OcrMode, evaluate_layout_readiness
from app.services.invoice.pipeline import process_invoice
from app.tenant_ids import TESTING_TENANT_UUID
from tests.pipeline_test_helpers import patch_confidence_gate_pass, patch_pre_ocr_gates_pass


def _dt_definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-03",
        title="Test invoice",
        shortTitle="Test",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
        requiredFields=["vendor", "total", "gst"],
        extractionFields=["vendor", "total", "gst"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def _good_ocr() -> OcrArtifact:
    text = "TAX INVOICE from Acme Pty Ltd ABN 12 345 678 901 invoice #INV-001 total $120.00 GST included"
    return OcrArtifact(
        success=True,
        sparse=False,
        text=text,
        text_length=len(text),
        di_model="prebuilt-layout",
    )


def test_ocr_quality_confirm_rejects_sparse_ocr() -> None:
    ocr = OcrArtifact(
        success=True,
        sparse=True,
        text="blurry photo",
        text_length=12,
        di_model="prebuilt-layout",
    )
    result = evaluate_ocr_quality_confirm(ocr, ai_cfg=AiClassificationConfig())
    assert not result.passed
    assert "OCR_SPARSE" in result.review_reasons
    # Back-compat alias
    assert not evaluate_image_quality_gate(ocr, ai_cfg=AiClassificationConfig()).passed


def test_ocr_quality_confirm_rejects_short_text() -> None:
    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text="short",
        text_length=5,
        di_model="prebuilt-layout",
    )
    result = evaluate_ocr_quality_confirm(ocr, ai_cfg=AiClassificationConfig())
    assert not result.passed
    assert "IMAGE_QUALITY_LOW" in result.review_reasons


def test_pre_ocr_blank_image_is_severe(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    path = tmp_path / "blank.png"
    Image.new("RGB", (400, 400), color=(255, 255, 255)).save(path)
    result = evaluate_pre_ocr_image_quality(path)
    assert not result.passed
    assert result.severity == "severe"
    assert any(s.name == "blank_page" for s in result.signals)


def test_pre_ocr_tiny_image_is_severe(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    path = tmp_path / "tiny.png"
    Image.new("RGB", (40, 40), color=(0, 0, 0)).save(path)
    # Paint some contrast so blank doesn't dominate
    img = Image.new("RGB", (40, 40), color=(0, 0, 0))
    for x in range(40):
        img.putpixel((x, x % 40), (255, 255, 255))
    img.save(path)
    result = evaluate_pre_ocr_image_quality(path)
    assert not result.passed
    assert any(s.name == "tiny_dimensions" for s in result.signals)


def test_pre_ocr_normal_scan_passes(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image
    from PIL import ImageDraw

    path = tmp_path / "scan.png"
    img = Image.new("RGB", (800, 1100), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, 760, 1060), outline=(20, 20, 20), width=3)
    for y in range(80, 1000, 28):
        draw.line((60, y, 740, y), fill=(30, 30, 30), width=2)
    img.save(path)
    result = evaluate_pre_ocr_image_quality(path)
    assert result.passed
    assert result.severity in {"pass", "warn"}
    # Skew/orientation/mild contrast must not be severe on a normal scan
    assert all(
        s.level != "severe" or s.name in {"raster_open_failed", "blank_page", "tiny_dimensions"}
        for s in result.signals
    )


def test_layout_readiness_image_routes_enhanced_scan(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    path = tmp_path / "photo.jpg"
    Image.new("RGB", (600, 800), color=(200, 200, 200)).save(path)
    result = evaluate_layout_readiness(path)
    assert result.ocr_mode == OcrMode.ENHANCED_SCAN


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
    definition = _dt_definition()
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
        dt_definition=definition,
        confirmed_dt="DT-03",
    )
    assert not result.passed
    assert result.low_confidence_fields.get("gst") == pytest.approx(0.4)
    assert "gst" in result.gate_fields
    assert "FIELD_CONFIDENCE_LOW" in result.review_reasons


def test_field_confidence_gate_ignores_absent_invoice_no_for_permit() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-02",
        confidence=0.9,
        perspective="purchase",
        vendor="Spectra",
        invoice_no="INV-999",
        field_confidence={"invoice_no": 0.2, "vendor": 0.95},
    )
    definition = _dt_definition(
        code="DT-02",
        playbookProfile="supporting",
        requiredFields=["vendor", "permit_no"],
        extractionFields=["vendor", "permit_no", "consignment_ref"],
        absentFields=["invoice_no", "due_date", "total"],
    )
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
        dt_definition=definition,
        confirmed_dt="DT-02",
    )
    assert result.passed
    assert "invoice_no" not in result.gate_fields
    assert "invoice_no" not in result.low_confidence_fields


def test_field_confidence_gate_skips_low_llm_when_merge_filled_field() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-01",
        confidence=0.9,
        perspective="purchase",
        vendor="Acme Pty Ltd",
        due_date="",
        field_confidence={"due_date": 0.3, "vendor": 0.95},
    )
    definition = _dt_definition(
        code="DT-01",
        requiredFields=["vendor", "total", "due_date"],
        extractionFields=["vendor", "total", "due_date"],
    )
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        vendor="Acme Pty Ltd",
        currency="AUD",
    )
    parsed = InvoiceData(
        vendor="Acme Pty Ltd",
        due_date=date(2026, 4, 20),
        total=Decimal("120.00"),
    )
    result = evaluate_field_confidence_gate(
        llm,
        ai_cfg=AiClassificationConfig(min_field_extract_confidence=0.65),
        dt_definition=definition,
        parsed=parsed,
        invoice=invoice,
        confirmed_dt="DT-01",
    )
    assert result.passed
    assert "due_date" not in result.low_confidence_fields


@pytest.mark.asyncio
async def test_pipeline_ocr_quality_confirm_blocks_classify(
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
        raise AssertionError("classify must not run when OCR quality confirm fails")

    patch_pre_ocr_gates_pass(monkeypatch)
    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.classify_only",
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

    async def _fake_extract(*_args, **_kwargs):
        from app.services.extraction.document_ai_provider import ExtractFieldsResult

        return ExtractFieldsResult(
            llm=LlmDocumentResult(
                suggested_dt="DT-03",
                confidence=0.92,
                perspective="purchase",
                vendor="Acme Pty Ltd",
                total="120.00",
                gst="10.00",
                seller=LlmParty(name="Acme Pty Ltd"),
                field_confidence={"gst": 0.35, "total": 0.95, "vendor": 0.9},
            ),
            ocr=ocr,
        )

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    async def _no_vendor_hold(_session, _inv) -> bool:
        return False

    async def _passing_validations(*_args, **_kwargs):
        from app.services.rule_book.validator import ValidationResult

        return [ValidationResult(rule="VR01", passed=True, message="ok", skipped=False)]

    dt_def = _dt_definition(
        code="DT-01",
        requiredFields=["vendor", "total", "gst"],
        extractionFields=["vendor", "total", "gst"],
    )

    from app.services.invoice.invoice_pipeline_phases import FieldConfidenceGateResult

    def _failing_field_conf(*_args, **_kwargs) -> FieldConfidenceGateResult:
        return FieldConfidenceGateResult(
            passed=False,
            low_confidence_fields={"gst": 0.35},
            min_confidence=0.65,
            review_reasons=["FIELD_CONFIDENCE_LOW"],
            gate_fields=["gst"],
            confirmed_dt="DT-01",
        )

    patch_confidence_gate_pass(monkeypatch)
    patch_pre_ocr_gates_pass(monkeypatch)
    monkeypatch.setattr(
        "app.services.invoice.pipeline.evaluate_field_confidence_gate",
        _failing_field_conf,
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline.get_document_type_definition",
        lambda *_args, **_kwargs: dt_def,
    )
    monkeypatch.setattr("app.services.invoice.pipeline.apply_vendor_hold_if_needed", _no_vendor_hold)
    monkeypatch.setattr("app.services.invoice.pipeline.run_all_validations", _passing_validations)
    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.read_for_classification",
        _fake_read,
    )
    monkeypatch.setattr(
        "app.services.invoice.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.invoice.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.extraction.document_ai_provider.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.invoice.pipeline.sync_invoice_blob_path", _noop_sync)

    from sqlalchemy import select

    from app.models.audit import AuditLog

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.vendor and "Acme" in inv.vendor
    rows = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.invoice_id == inv.id)
        )
    ).scalars().all()
    assert "ocr_quality_confirm_passed" in rows or "image_quality_gate_passed" in rows
    assert "field_confidence_evaluated" in rows
