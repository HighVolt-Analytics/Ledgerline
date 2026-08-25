"""Marginal understand-confidence forces DI invoice-model merge."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.vision_dt_extract import VisionDtExtractResult

_RICH_TEXT = (
    "TAX INVOICE\n"
    "Acme Supplies Pty Ltd\n"
    "Consulting services rendered in March for project Alpha.\n"
    "Subtotal 100.00\n"
    "GST 10.00\n"
    "Total 120.00\n"
    "Payment due within thirty days of the invoice date shown above.\n"
)


def _posting_dt() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-99",
        title="Tax Invoice",
        shortTitle="Tax Invoice",
        klass="Transactional",
        posting="Yes",
        enabled=True,
        extractionFields=["vendor", "total", "subtotal", "gst"],
        requiredFields=["vendor"],
        routeTarget="Purchase Management",
    )


def _stub_evaluate_deps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    di_enabled: bool,
    extract_capture: dict[str, object] | None = None,
    enrich_calls: list | None = None,
) -> Path:
    from app.services.extraction.document_ai_provider import ExtractFieldsResult
    from app.services.invoice.vision_dt_extract import _minimal_vision_ocr

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    capture = extract_capture if extract_capture is not None else {}

    @contextmanager
    def _open_pdf(*_args, **_kwargs):
        yield pdf

    async def _extract(*_args, **kwargs):
        capture.update(kwargs)
        return ExtractFieldsResult(
            llm=SimpleNamespace(confidence=0.9, raw={}),
            ocr=_minimal_vision_ocr(page_count=1),
        )

    async def _translate(parsed, **_k):
        return parsed, {}

    monkeypatch.setattr(
        "app.services.shared.file_storage.open_pdf_for_reading",
        _open_pdf,
    )
    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.extract_fields",
        _extract,
    )
    monkeypatch.setattr(
        "app.services.extraction.document_intelligence.is_di_enabled",
        lambda: di_enabled,
    )
    monkeypatch.setattr(
        "app.services.extraction.llm_document_service.llm_result_to_invoice_data",
        lambda *_a, **_k: InvoiceData(
            vendor="Acme",
            total=Decimal("120.00"),
            subtotal=Decimal("100.00"),
            gst=Decimal("10.00"),
        ),
    )
    monkeypatch.setattr(
        "app.services.extraction.field_translation_service.apply_field_translation",
        _translate,
    )
    monkeypatch.setattr(
        "app.services.invoice.vision_header_reconcile.resolve_header_grounding_text",
        lambda _path: (_RICH_TEXT, {"source": "local"}),
    )
    monkeypatch.setattr(
        "app.services.invoice.pipeline._apply_parsed_to_invoice",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.purchase.team_expense_service.stamp_team_expense_employee_identity",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.invoice.vision_posting_continue.vision_header_ok_from_invoice",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_pipeline_service.payable_fields_complete",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app.services.invoice.due_date_defaults.apply_due_on_receipt_to_parsed",
        lambda parsed, *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.invoice.due_date_defaults.apply_due_on_receipt_to_invoice",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.services.extraction.line_item_extraction_policy.team_expense_hard_requires_line_items",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app.services.audit.audit_service.log_event",
        AsyncMock(),
    )
    if enrich_calls is not None:
        from app.services.extraction.extraction_field_values import (
            enrich_parsed_from_ocr as _real_enrich,
        )

        def _enrich(parsed, ocr, **kwargs):
            enrich_calls.append({"ocr": ocr, **kwargs})
            return _real_enrich(parsed, ocr, **kwargs)

        monkeypatch.setattr(
            "app.services.extraction.extraction_field_values.enrich_parsed_from_ocr",
            _enrich,
        )
    return pdf


async def _evaluate(invoice, *, understand_confidence: float | None):
    from app.services.extraction.document_ai_provider import DocumentAiProvider
    from app.services.invoice.vision_dt_extract import evaluate_vision_dt_extract
    from app.services.tenant.tenant_org_context import OrgContext

    return await evaluate_vision_dt_extract(
        AsyncMock(),
        invoice,
        org=OrgContext(),
        document_types=[_posting_dt()],
        confirmed_dt="DT-99",
        doc_provider=DocumentAiProvider.CLAUDE_VISION,
        definition=_posting_dt(),
        understand_confidence=understand_confidence,
    )


@pytest.mark.asyncio
async def test_evaluate_forces_invoice_model_when_confidence_marginal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.tenant_ids import TESTING_TENANT_UUID

    capture: dict[str, object] = {}
    enrich_calls: list = []
    pdf = _stub_evaluate_deps(
        monkeypatch,
        tmp_path,
        di_enabled=True,
        extract_capture=capture,
        enrich_calls=enrich_calls,
    )
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        raw_file_path=str(pdf),
        document_type_code="DT-99",
        vendor="Acme",
    )
    result = await _evaluate(invoice, understand_confidence=0.62)
    assert result.success is True
    assert capture.get("force_invoice_model") is True
    assert result.marginal_confidence_forced_di is True
    assert result.marginal_confidence_no_di is False
    assert len(enrich_calls) == 1
    assert result.needs_review is False


@pytest.mark.asyncio
async def test_evaluate_does_not_force_invoice_model_when_high_confidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.tenant_ids import TESTING_TENANT_UUID

    capture: dict[str, object] = {}
    enrich_calls: list = []
    pdf = _stub_evaluate_deps(
        monkeypatch,
        tmp_path,
        di_enabled=True,
        extract_capture=capture,
        enrich_calls=enrich_calls,
    )
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        raw_file_path=str(pdf),
        document_type_code="DT-99",
        vendor="Acme",
    )
    result = await _evaluate(invoice, understand_confidence=0.85)
    assert result.success is True
    assert capture.get("force_invoice_model") is False
    assert result.marginal_confidence_forced_di is False
    assert enrich_calls == []


@pytest.mark.asyncio
async def test_evaluate_needs_review_when_marginal_and_di_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.tenant_ids import TESTING_TENANT_UUID

    capture: dict[str, object] = {}
    pdf = _stub_evaluate_deps(
        monkeypatch, tmp_path, di_enabled=False, extract_capture=capture
    )
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        raw_file_path=str(pdf),
        document_type_code="DT-99",
        vendor="Acme",
    )
    result = await _evaluate(invoice, understand_confidence=0.60)
    assert result.success is True
    assert capture.get("force_invoice_model") is False
    assert result.marginal_confidence_no_di is True
    assert result.needs_review is True


@pytest.mark.asyncio
async def test_phase_emits_forced_di_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.invoice import invoice_pipeline_phases as phases

    events: list[str] = []

    async def _log(_session, event, **_kwargs):
        events.append(event)

    async def _evaluate(*_args, **_kwargs):
        return VisionDtExtractResult(
            success=True,
            understand_confidence=0.62,
            marginal_confidence_forced_di=True,
        )

    monkeypatch.setattr(phases, "log_event", _log)
    monkeypatch.setattr(
        "app.services.invoice.vision_dt_extract.evaluate_vision_dt_extract",
        _evaluate,
    )
    await phases.phase_vision_dt_extract(
        AsyncMock(),
        SimpleNamespace(id=42, vendor="Acme", total=None, invoice_no=None),
        org=SimpleNamespace(),
        document_types=[],
        confirmed_dt="DT-01",
        doc_provider=SimpleNamespace(value="claude_vision"),
        document_ai_provider="claude_vision",
        understand_confidence=0.62,
    )
    assert "vision_marginal_confidence_forced_di" in events
    assert "vision_marginal_confidence_no_di_available" not in events


@pytest.mark.asyncio
async def test_phase_emits_no_di_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.invoice import invoice_pipeline_phases as phases

    events: list[str] = []

    async def _log(_session, event, **_kwargs):
        events.append(event)

    async def _evaluate(*_args, **_kwargs):
        return VisionDtExtractResult(
            success=True,
            needs_review=True,
            understand_confidence=0.60,
            marginal_confidence_no_di=True,
        )

    monkeypatch.setattr(phases, "log_event", _log)
    monkeypatch.setattr(
        "app.services.invoice.vision_dt_extract.evaluate_vision_dt_extract",
        _evaluate,
    )
    await phases.phase_vision_dt_extract(
        AsyncMock(),
        SimpleNamespace(id=42, vendor="Acme", total=None, invoice_no=None),
        org=SimpleNamespace(),
        document_types=[],
        confirmed_dt="DT-01",
        doc_provider=SimpleNamespace(value="claude_vision"),
        document_ai_provider="claude_vision",
        understand_confidence=0.60,
    )
    assert "vision_marginal_confidence_no_di_available" in events
    assert "vision_marginal_confidence_forced_di" not in events


@pytest.mark.asyncio
async def test_phase_forwards_understand_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.invoice import invoice_pipeline_phases as phases

    seen: dict[str, object] = {}

    async def _evaluate(*_args, **kwargs):
        seen.update(kwargs)
        return VisionDtExtractResult(success=True)

    monkeypatch.setattr(phases, "log_event", AsyncMock())
    monkeypatch.setattr(
        "app.services.invoice.vision_dt_extract.evaluate_vision_dt_extract",
        _evaluate,
    )
    await phases.phase_vision_dt_extract(
        AsyncMock(),
        SimpleNamespace(id=7, vendor=None, total=None, invoice_no=None),
        org=SimpleNamespace(),
        document_types=[],
        confirmed_dt="DT-01",
        doc_provider=SimpleNamespace(value="claude_vision"),
        document_ai_provider="claude_vision",
        understand_confidence=0.62,
    )
    assert seen.get("understand_confidence") == 0.62


def test_pipeline_threads_understand_confidence_into_both_dt_extracts() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "invoice"
        / "pipeline.py"
    ).read_text(encoding="utf-8")
    hits = 0
    cursor = 0
    while True:
        start = src.find("phase_vision_dt_extract(", cursor)
        if start < 0:
            break
        end = src.find(")", start)
        block = src[start:end]
        if "understand_confidence=understand.confidence" in block:
            hits += 1
        cursor = start + 1
    assert hits == 2
    assert src.count("phase_vision_dt_extract(") == 2
