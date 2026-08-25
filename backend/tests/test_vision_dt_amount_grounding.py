"""DT-scoped money grounding against independently pulled PDF text."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice.vision_dt_extract import (
    VisionDtExtractResult,
    vision_dt_extract_audit_detail,
)
from app.services.invoice.vision_header_reconcile import ground_parsed_money_fields

_RICH_TEXT = (
    "TAX INVOICE\n"
    "Acme Supplies Pty Ltd\n"
    "Consulting services rendered in March for project Alpha.\n"
    "Subtotal 100.00\n"
    "GST 10.00\n"
    "Total 120.00\n"
    "Payment due within thirty days of the invoice date shown above.\n"
)


def test_ungrounded_total_is_cleared_not_kept() -> None:
    parsed = InvoiceData(
        total=Decimal("99999.00"),
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        extracted_fields={"total": "99999.00", "subtotal": "100.00"},
    )
    updated, detail = ground_parsed_money_fields(parsed, _RICH_TEXT, text_source="local")
    assert updated.total is None
    assert "total" in detail["cleared"]
    assert updated.subtotal == Decimal("100.00")
    assert updated.gst == Decimal("10.00")
    assert "total" not in (updated.extracted_fields or {})
    assert detail["skipped"] is False


def test_grounded_total_passes_through_unchanged() -> None:
    parsed = InvoiceData(
        total=Decimal("120.00"),
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
    )
    updated, detail = ground_parsed_money_fields(parsed, _RICH_TEXT, text_source="local")
    assert updated.total == Decimal("120.00")
    assert updated.subtotal == Decimal("100.00")
    assert updated.gst == Decimal("10.00")
    assert "total" not in detail["cleared"]
    assert "total" in detail["kept"]
    assert detail["skipped"] is False


def test_thin_text_skips_grounding_and_keeps_vision_total() -> None:
    parsed = InvoiceData(total=Decimal("99999.00"), currency="USD")
    updated, detail = ground_parsed_money_fields(parsed, "short", text_source="local_thin")
    assert updated.total == Decimal("99999.00")
    assert updated.currency == "USD"
    assert detail["skipped"] is True
    assert detail["cleared"] == []
    assert "thin" in (detail.get("reason") or "")


def test_ungrounded_line_amount_is_cleared() -> None:
    parsed = InvoiceData(
        total=Decimal("120.00"),
        line_items=[
            ParsedLineItem(description="Widget", amount=Decimal("88888.00")),
            ParsedLineItem(description="Fee", amount=Decimal("120.00")),
        ],
    )
    updated, detail = ground_parsed_money_fields(parsed, _RICH_TEXT)
    assert updated.line_items[0].amount is None
    assert updated.line_items[1].amount == Decimal("120.00")
    assert "line_items[0].amount" in detail["cleared"]


def test_audit_detail_includes_amount_grounding_cleared() -> None:
    detail = vision_dt_extract_audit_detail(
        VisionDtExtractResult(
            success=True,
            amount_grounding_cleared=("total",),
            amount_grounding_text_source="local",
        )
    )
    assert detail["amount_grounding_cleared"] == ["total"]
    assert detail["amount_grounding_text_source"] == "local"


@pytest.mark.asyncio
async def test_phase_emits_vision_dt_amount_ungrounded_when_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice import invoice_pipeline_phases as phases

    events: list[tuple[str, dict]] = []

    async def _log(_session, event, **kwargs):
        events.append((event, kwargs.get("detail") or {}))

    async def _evaluate(*_args, **_kwargs):
        return VisionDtExtractResult(
            success=True,
            amount_grounding_cleared=("total", "gst"),
            amount_grounding_text_source="local",
        )

    monkeypatch.setattr(phases, "log_event", _log)
    monkeypatch.setattr(
        "app.services.invoice.vision_dt_extract.evaluate_vision_dt_extract",
        _evaluate,
    )

    invoice = SimpleNamespace(id=42, vendor="Acme", total=None, invoice_no="INV-1")
    result = await phases.phase_vision_dt_extract(
        AsyncMock(),
        invoice,
        org=SimpleNamespace(),
        document_types=[],
        confirmed_dt="DT-01",
        doc_provider=SimpleNamespace(value="claude_vision"),
        document_ai_provider="claude_vision",
    )
    assert result.amount_grounding_cleared == ("total", "gst")
    ungrounded = [detail for event, detail in events if event == "vision_dt_amount_ungrounded"]
    assert len(ungrounded) == 1
    assert ungrounded[0]["cleared"] == ["total", "gst"]
    assert ungrounded[0]["text_source"] == "local"


@pytest.mark.asyncio
async def test_phase_does_not_emit_ungrounded_when_amounts_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice import invoice_pipeline_phases as phases

    events: list[str] = []

    async def _log(_session, event, **_kwargs):
        events.append(event)

    async def _evaluate(*_args, **_kwargs):
        return VisionDtExtractResult(success=True)

    monkeypatch.setattr(phases, "log_event", _log)
    monkeypatch.setattr(
        "app.services.invoice.vision_dt_extract.evaluate_vision_dt_extract",
        _evaluate,
    )

    await phases.phase_vision_dt_extract(
        AsyncMock(),
        SimpleNamespace(id=42, vendor=None, total=Decimal("120"), invoice_no=None),
        org=SimpleNamespace(),
        document_types=[],
        confirmed_dt="DT-01",
        doc_provider=SimpleNamespace(value="claude_vision"),
        document_ai_provider="claude_vision",
    )
    assert "vision_dt_amount_ungrounded" not in events
    assert "vision_dt_fields_extracted" in events


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


@pytest.mark.asyncio
async def test_evaluate_sets_needs_review_when_total_does_not_ground(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Cleared invented total on evaluate_vision_dt_extract → needs_review=True."""
    from contextlib import contextmanager

    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.extraction.document_ai_provider import (
        DocumentAiProvider,
        ExtractFieldsResult,
    )
    from app.services.invoice.vision_dt_extract import (
        _minimal_vision_ocr,
        evaluate_vision_dt_extract,
    )
    from app.services.tenant.tenant_org_context import OrgContext
    from app.tenant_ids import TESTING_TENANT_UUID

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")

    @contextmanager
    def _open_pdf(*_args, **_kwargs):
        yield pdf

    async def _extract(*_args, **_kwargs):
        return ExtractFieldsResult(
            llm=SimpleNamespace(confidence=0.9, raw={}),
            ocr=_minimal_vision_ocr(page_count=1),
        )

    monkeypatch.setattr(
        "app.services.shared.file_storage.open_pdf_for_reading",
        _open_pdf,
    )
    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.extract_fields",
        _extract,
    )
    monkeypatch.setattr(
        "app.services.extraction.llm_document_service.llm_result_to_invoice_data",
        lambda *_a, **_k: InvoiceData(
            vendor="Acme",
            total=Decimal("99999.00"),
            subtotal=Decimal("100.00"),
            gst=Decimal("10.00"),
        ),
    )
    async def _translate(parsed, **_k):
        return parsed, {}

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

    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        raw_file_path=str(pdf),
        document_type_code="DT-99",
        vendor="Acme",
    )
    result = await evaluate_vision_dt_extract(
        AsyncMock(),
        invoice,
        org=OrgContext(),
        document_types=[_posting_dt()],
        confirmed_dt="DT-99",
        doc_provider=DocumentAiProvider.CLAUDE_VISION,
        definition=_posting_dt(),
    )
    assert result.success is True
    assert "total" in result.amount_grounding_cleared
    assert result.needs_review is True


def test_dt_extract_needs_review_blocks_understood_posting() -> None:
    """Pipeline header_ok formula: needs_review on DT extract stops posting continue."""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.invoice.vision_posting_continue import (
        vision_posting_skip_reason,
        vision_should_continue_posting,
    )
    from app.tenant_ids import TESTING_TENANT_UUID

    result = VisionDtExtractResult(
        success=True,
        needs_review=True,
        amount_grounding_cleared=("total",),
    )
    # Same derivation as process_invoice after phase_vision_dt_extract
    # (pipeline.py: header_ok = success and not needs_review).
    header_ok = bool(result.success) and not bool(result.needs_review)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        document_type_code="DT-99",
    )
    assert header_ok is False
    assert vision_should_continue_posting(inv, _posting_dt(), header_ok=header_ok) is False
    assert vision_posting_skip_reason(inv, _posting_dt(), header_ok=header_ok) == "header_not_ok"
