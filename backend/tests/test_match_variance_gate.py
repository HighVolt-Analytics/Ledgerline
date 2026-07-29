"""Variance match gate and posting-resume tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.models.delivery_note import DeliveryNote
from app.models.sales_order import SalesOrder
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.schemas.uom_conversion import PurchaseMatchConfig
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_playbook_service import PlaybookGateResult
from app.services.extraction.document_ai_provider import ExtractFieldsResult
from app.services.invoice.file_validity_gate import FileValidityResult
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, ROUTE_SALES
from app.services.invoice.pipeline import process_invoice
from app.services.match.match_variance_gate_service import (
    evaluate_match_variance_gate,
    resume_invoice_posting_after_variance_approval,
)
from app.services.purchase.purchase_match_service import approve_purchase_variance
from app.services.rule_book.account_mapper import AccountMapping
from app.tenant_child_tables import journal_entries_for_invoice
from app.tenant_ids import TESTING_TENANT_UUID
from tests.rule_book_test_helpers import demo_rule_book_config, mapping_doc_type_config


def _doc_type_config(
    *,
    code: str,
    ledger: str,
    title: str,
    route_target: str,
    match_mode: str,
) -> RuleBookConfigPayload:
    from app.schemas.document_type import DocumentTypeDefinition, DocumentTypePostTo
    from app.schemas.playbook_policy import MatchPolicy

    definition = DocumentTypeDefinition(
        code=code,
        title=title,
        short_title=title,
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        route_target=route_target,
        post_to=DocumentTypePostTo(ledger=ledger),
        match_policy=MatchPolicy(mode=match_mode),
    )
    config = demo_rule_book_config()
    existing = [dt for dt in config.document_types if dt.code.strip().upper() != code.strip().upper()]
    merged = config.model_copy(update={"document_types": [definition, *existing]})
    if not merged.chart_of_accounts:
        merged = merged.model_copy(update={"chart_of_accounts": demo_rule_book_config().chart_of_accounts})
    return merged


def _purchase_config() -> RuleBookConfigPayload:
    return _doc_type_config(
        code="DT-09",
        ledger="Marketing Expense",
        title="PO-based goods invoice",
        route_target=ROUTE_PURCHASE,
        match_mode="three_way_po_grn",
    )


def _sales_config() -> RuleBookConfigPayload:
    return _doc_type_config(
        code="DT-07",
        ledger="Operating Expenses",
        title="Sales invoice",
        route_target=ROUTE_SALES,
        match_mode="three_way_so_dn",
    )


async def _build_purchase_variance_triplet(
    db_session: AsyncSession,
    *,
    po_qty: Decimal = Decimal("120"),
    grn_qty: Decimal = Decimal("1"),
    inv_qty: Decimal = Decimal("120"),
    unit_price: Decimal = Decimal("3466.6667"),
    po_number: str = "PO-VAR-GATE-1",
) -> tuple[PurchaseOrder, Invoice]:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Everest Furnishings",
        po_reference=po_number,
        invoice_no=po_number,
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=po_qty * unit_price,
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-09",
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=po_doc.id,
            description="Stock",
            qty=po_qty,
            unit_price=unit_price,
            amount=po_qty * unit_price,
        )
    )
    await db_session.flush()

    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number=po_number,
        vendor="Everest Furnishings",
        po_qty=po_qty,
        po_unit_price=unit_price,
        po_document_id=po_doc.id,
    )
    db_session.add(po)
    await db_session.flush()
    db_session.add(
        GoodsReceipt(
            tenant_id=TESTING_TENANT_UUID,
            purchase_order_id=po.id,
            grn_qty=grn_qty,
            grn_date=date(2026, 6, 13),
        )
    )
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Everest Furnishings",
        po_reference=po_number,
        invoice_no="INV-VAR-GATE-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        document_type_code="DT-09",
        document_type_confidence=0.95,
        subtotal=inv_qty * unit_price,
        gst=Decimal("74880"),
        total=inv_qty * unit_price + Decimal("74880"),
        invoice_date=date(2026, 6, 15),
        due_date=date(2026, 7, 1),
        status=InvoiceStatus.PENDING,
        currency="INR",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Stock",
            qty=inv_qty,
            unit_price=unit_price,
            amount=inv_qty * unit_price,
        )
    )
    await db_session.flush()
    po.invoice_id = inv.id
    await db_session.flush()
    return po, inv


async def _reload_invoice(db_session: AsyncSession, invoice_id: int) -> Invoice:
    return (
        await db_session.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()


async def _build_sales_variance_triplet(
    db_session: AsyncSession,
    *,
    so_qty: Decimal = Decimal("10"),
    dn_qty: Decimal = Decimal("1"),
    inv_qty: Decimal = Decimal("10"),
    unit_price: Decimal = Decimal("45"),
    so_number: str = "SO-VAR-GATE-1",
) -> tuple[SalesOrder, Invoice]:
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number=so_number,
        customer="Harbour View Hotel",
        so_qty=so_qty,
        so_unit_price=unit_price,
    )
    db_session.add(so)
    await db_session.flush()
    db_session.add(
        DeliveryNote(
            tenant_id=TESTING_TENANT_UUID,
            sales_order_id=so.id,
            dn_qty=dn_qty,
            dn_date=date(2026, 6, 1),
        )
    )
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference=so_number,
        invoice_no="INV-SO-VAR-1",
        route_target=ROUTE_SALES,
        sales_document_type="invoice",
        document_type_code="DT-07",
        document_type_confidence=0.9,
        subtotal=inv_qty * unit_price,
        gst=Decimal("45"),
        total=inv_qty * unit_price + Decimal("45"),
        due_date=date(2026, 7, 1),
        status=InvoiceStatus.PENDING,
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Catering",
            qty=inv_qty,
            unit_price=unit_price,
            amount=inv_qty * unit_price,
        )
    )
    await db_session.flush()
    so.invoice_id = inv.id
    await db_session.flush()
    return so, inv


def _patch_pipeline_to_mapping(
    monkeypatch: pytest.MonkeyPatch,
    config: RuleBookConfigPayload,
    tmp_path,
    *,
    po_number: str = "PO-VAR-GATE-1",
) -> str:
    pdf_path = tmp_path / "var-gate.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    ocr_text = "TAX INVOICE with enough readable OCR text for quality gate to pass easily here"
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

    async def _load_config(_session, _tenant_id):
        return config

    from tests.pipeline_test_helpers import patch_pre_ocr_gates_pass

    patch_pre_ocr_gates_pass(monkeypatch)
    monkeypatch.setattr("app.services.invoice.file_validity_gate.evaluate_file_validity", lambda *_a, **_k: FileValidityResult(passed=True, rejection_code=None, detail="ok"))
    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.read_for_classification", _fake_read)
    async def _fake_extract(*_args, **_kwargs) -> ExtractFieldsResult:
        return ExtractFieldsResult(
            llm=LlmDocumentResult(
                suggested_dt="DT-09",
                confidence=0.95,
                reasoning="t",
                perspective="purchase",
                po_reference=po_number,
                vendor="Everest Furnishings",
                subtotal=Decimal("416000"),
                total=Decimal("490880"),
                gst=Decimal("74880"),
                line_items=[
                    {
                        "description": "Stock",
                        "qty": "120",
                        "unit_price": "3466.6667",
                        "amount": "416000",
                    }
                ],
            ),
            ocr=ocr,
            di_enrich_detail=None,
        )

    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.invoice.pipeline.extract_fields", _fake_extract)
    async def _apply_eval(session, inv, **_kwargs):
        inv.route_target = ROUTE_PURCHASE
        inv.purchase_document_type = PurchaseDocumentType.INVOICE.value
        inv.evaluation_status = "auto_coded"

    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", AsyncMock())
    monkeypatch.setattr("app.services.pipeline.apply_invoice_evaluation", _apply_eval)
    monkeypatch.setattr("app.services.invoice.pipeline.apply_invoice_evaluation", _apply_eval)
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
    monkeypatch.setattr("app.services.invoice.pipeline.load_config_for_tenant", _load_config)
    monkeypatch.setattr("app.services.pipeline.load_config_for_tenant", _load_config)
    monkeypatch.setattr(
        "app.services.invoice.pipeline._resolve_header_mapping",
        lambda *_a, **_k: (
            AccountMapping("6130", "Marketing Expense"),
            type("D", (), {"rule_type": "document_type", "match_reason": "test"})(),
        ),
    )
    monkeypatch.setattr("app.services.pipeline.requires_gl_mapping_review", lambda *_a, **_k: False)
    monkeypatch.setattr("app.services.pipeline.apply_document_type_approval_gate", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.invoice.pipeline.apply_document_type_approval_gate", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.pipeline.apply_vendor_hold_if_needed", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.invoice.pipeline._vendor_hold_unless_skipped", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.pipeline.apply_team_expense_approval_gate", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.invoice.pipeline.reconcile_daily", AsyncMock(return_value=type("R", (), {"halted": False})()))
    monkeypatch.setattr("app.services.invoice.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr("app.services.pipeline.reconcile_daily", AsyncMock(return_value=type("R", (), {"halted": False})()))
    monkeypatch.setattr("app.services.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr("app.services.integration.publish_service.publish_invoice_to_ledger", AsyncMock())
    monkeypatch.setattr("app.services.invoice.pipeline._vendor_hold_unless_skipped", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.pipeline.send_notification", lambda *_a, **_k: None)
    return str(pdf_path)


@pytest.mark.asyncio
async def test_evaluate_gate_blocks_purchase_qty_variance(db_session: AsyncSession) -> None:
    config = _purchase_config()
    po, inv = await _build_purchase_variance_triplet(db_session)
    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is True
    assert gate.outcome is not None
    assert gate.outcome.status == "Qty Variance"
    assert gate.variance_approved is False
    assert gate.anchor_number == po.po_number
    expected = round(float(Decimal("120") - Decimal("1")) * float(Decimal("3466.6667")), 2)
    assert gate.outcome.detail.get("qty_variance_value") == expected


@pytest.mark.asyncio
async def test_evaluate_gate_passes_when_variance_approved(db_session: AsyncSession) -> None:
    config = _purchase_config()
    po, inv = await _build_purchase_variance_triplet(db_session)
    po.variance_approved = True
    await db_session.flush()
    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is False


@pytest.mark.asyncio
async def test_evaluate_gate_respects_qty_tolerance(db_session: AsyncSession) -> None:
    config = _purchase_config().model_copy(
        update={"purchase_match": PurchaseMatchConfig(qty_tolerance_pct=10.0)}
    )
    po, inv = await _build_purchase_variance_triplet(
        db_session,
        po_qty=Decimal("100"),
        grn_qty=Decimal("95"),
        inv_qty=Decimal("100"),
        unit_price=Decimal("10"),
        po_number="PO-TOL-1",
    )
    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is False


@pytest.mark.asyncio
async def test_pipeline_blocks_variance_before_journal(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _purchase_config()
    po, inv = await _build_purchase_variance_triplet(db_session)
    _patch_pipeline_to_mapping(monkeypatch, config, tmp_path, po_number=po.po_number)

    from app.services.purchase import purchase_match_service as purchase_match_module

    _original_load_po = purchase_match_module.load_purchase_order_for_invoice

    async def _load_po_for_invoice(db, invoice):
        linked = await _original_load_po(db, invoice)
        if linked is not None:
            return linked
        if invoice.id == inv.id:
            return (
                await db.execute(
                    select(PurchaseOrder)
                    .where(PurchaseOrder.id == po.id)
                    .options(
                        selectinload(PurchaseOrder.goods_receipts).selectinload(GoodsReceipt.lines),
                        selectinload(PurchaseOrder.lines),
                    )
                )
            ).scalar_one()
        return None

    monkeypatch.setattr(
        purchase_match_module,
        "load_purchase_order_for_invoice",
        _load_po_for_invoice,
    )
    monkeypatch.setattr(
        "app.services.match.match_variance_gate_service.load_purchase_order_for_invoice",
        _load_po_for_invoice,
    )

    inv.raw_file_path = str(tmp_path / "var-gate.pdf")
    inv.file_hash = "var-gate-hash"
    inv.processing_overrides = {
        "skip_steps": ["image_quality", "classification", "validation", "line_gl_mapping"]
    }
    await db_session.flush()
    inv = await _reload_invoice(db_session, inv.id)

    await process_invoice(db_session, inv)
    await db_session.flush()

    assert inv.status == InvoiceStatus.EXCEPTION
    events = (
        await db_session.execute(
            select(AuditLog.event, AuditLog.detail).where(AuditLog.invoice_id == inv.id)
        )
    ).all()
    variance_events = [
        detail
        for event, detail in events
        if event == "three_way_match_variance_unapproved" and isinstance(detail, dict)
    ]
    assert len(variance_events) == 1
    assert variance_events[0].get("match_status") in {"Qty Variance", "Price Variance"}
    if variance_events[0].get("match_status") == "Qty Variance":
        assert abs(float(variance_events[0].get("qty_variance_value") or 0) - 412533.33) < 0.02
    journal_count = (
        await db_session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalar()
    assert journal_count == 0
    assert not any(event == "invoice_processed" for event, _ in events)


@pytest.mark.asyncio
async def test_resume_posting_after_variance_approval(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _purchase_config()
    po, inv = await _build_purchase_variance_triplet(db_session)
    vendor_before = inv.vendor
    subtotal_before = inv.subtotal
    total_before = inv.total

    await log_event(
        db_session,
        "three_way_match_variance_unapproved",
        invoice_id=inv.id,
        detail={"match_status": "Qty Variance", "qty_variance_value": 412533.33},
    )
    inv.status = InvoiceStatus.EXCEPTION
    await db_session.flush()

    ocr_called = {"value": False}
    extract_called = {"value": False}

    async def _block_ocr(*_args, **_kwargs):
        ocr_called["value"] = True
        raise AssertionError("phase_ocr should not run during variance resume")

    async def _block_extract(*_args, **_kwargs):
        extract_called["value"] = True
        raise AssertionError("extract_fields should not run during variance resume")

    monkeypatch.setattr("app.services.invoice.invoice_pipeline_phases.phase_ocr", _block_ocr)
    monkeypatch.setattr("app.services.pipeline.extract_fields", _block_extract)
    monkeypatch.setattr("app.services.invoice.pipeline.load_config_for_tenant", AsyncMock(return_value=config))
    monkeypatch.setattr("app.services.pipeline.load_config_for_tenant", AsyncMock(return_value=config))
    monkeypatch.setattr("app.services.pipeline.apply_vendor_hold_if_needed", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.invoice.pipeline._vendor_hold_unless_skipped", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.pipeline.apply_team_expense_approval_gate", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.invoice.pipeline.reconcile_daily", AsyncMock(return_value=type("R", (), {"halted": False})()))
    monkeypatch.setattr("app.services.invoice.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr("app.services.pipeline.reconcile_daily", AsyncMock(return_value=type("R", (), {"halted": False})()))
    monkeypatch.setattr("app.services.pipeline.save_reconciliation", AsyncMock())
    monkeypatch.setattr("app.services.integration.publish_service.publish_invoice_to_ledger", AsyncMock())
    monkeypatch.setattr("app.services.pipeline.send_notification", lambda *_a, **_k: None)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", AsyncMock())

    po.variance_approved = True
    await db_session.flush()
    inv = await _reload_invoice(db_session, inv.id)
    resumed = await resume_invoice_posting_after_variance_approval(db_session, inv, config=config)
    assert resumed is True
    assert inv.status == InvoiceStatus.PROCESSED
    assert inv.vendor == vendor_before
    assert inv.subtotal == subtotal_before
    assert inv.total == total_before
    assert ocr_called["value"] is False
    assert extract_called["value"] is False

    events = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.invoice_id == inv.id)
        )
    ).scalars().all()
    assert "variance_approval_reprocess_queued" in events
    assert "variance_approval_posting_resumed" in events
    assert events.count("three_way_match_variance_unapproved") == 1
    journal_count = (
        await db_session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalar()
    assert journal_count >= 1


@pytest.mark.asyncio
async def test_sales_gate_blocks_qty_variance(db_session: AsyncSession) -> None:
    config = _sales_config()
    so, inv = await _build_sales_variance_triplet(db_session)
    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is True
    assert gate.outcome is not None
    assert gate.outcome.status == "Qty Variance"
    assert gate.anchor_type == "sales"
    assert so.so_number == gate.anchor_number


def _purchase_two_way_config() -> RuleBookConfigPayload:
    return _doc_type_config(
        code="DT-09",
        ledger="Marketing Expense",
        title="PO-based goods invoice",
        route_target=ROUTE_PURCHASE,
        match_mode="two_way_po_ses",
    )


@pytest.mark.asyncio
async def test_two_way_po_price_variance_blocks(db_session: AsyncSession) -> None:
    config = _purchase_two_way_config()
    po_number = "PO-2WAY-PRICE"
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number=po_number,
        vendor="Vendor",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("40"),
    )
    db_session.add(po)
    await db_session.flush()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor",
        po_reference=po_number,
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        document_type_code="DT-09",
        subtotal=Decimal("600"),
        total=Decimal("600"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            qty=Decimal("10"),
            unit_price=Decimal("60"),
            amount=Decimal("600"),
        )
    )
    await db_session.flush()
    po.invoice_id = inv.id
    await db_session.flush()
    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is True
    assert gate.outcome is not None
    assert gate.outcome.status == "Price Variance"


@pytest.mark.asyncio
async def test_two_way_grn_qty_variance_blocks(db_session: AsyncSession) -> None:
    config = _purchase_config()
    grn_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor",
        invoice_no="GRN-REF-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.GRN.value,
        subtotal=Decimal("100"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(grn_inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=grn_inv.id,
            qty=Decimal("5"),
            unit_price=Decimal("20"),
            amount=Decimal("100"),
        )
    )
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor",
        invoice_no="GRN-REF-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        document_type_code="DT-09",
        subtotal=Decimal("200"),
        total=Decimal("200"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            qty=Decimal("10"),
            unit_price=Decimal("20"),
            amount=Decimal("200"),
        )
    )
    await db_session.flush()

    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is True
    assert gate.outcome is not None
    assert gate.outcome.status == "Qty Variance"


@pytest.mark.asyncio
async def test_clean_invoice_without_po_not_blocked(db_session: AsyncSession) -> None:
    config = _purchase_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Standalone Vendor",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        document_type_code="DT-09",
        subtotal=Decimal("100"),
        total=Decimal("100"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is False


@pytest.mark.asyncio
async def test_three_way_missing_grn_blocks_posting(db_session: AsyncSession) -> None:
    """Configured 3-way must not silently downgrade to 2-way when GRN is missing."""
    config = _purchase_config()
    po_number = "PO-NO-GRN-1"
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="No GRN Vendor",
        po_reference=po_number,
        invoice_no=po_number,
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("100"),
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-02",
    )
    db_session.add(po_doc)
    await db_session.flush()
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number=po_number,
        vendor="No GRN Vendor",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("10"),
        po_document_id=po_doc.id,
    )
    db_session.add(po)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="No GRN Vendor",
        po_reference=po_number,
        invoice_no="INV-NO-GRN-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        document_type_code="DT-09",
        subtotal=Decimal("100"),
        total=Decimal("100"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            qty=Decimal("10"),
            unit_price=Decimal("10"),
            amount=Decimal("100"),
        )
    )
    po.invoice_id = inv.id
    await db_session.flush()

    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is True
    assert gate.outcome is not None
    assert gate.outcome.status == "No GRN"
    assert gate.match_mode == "three_way_po_grn"


@pytest.mark.asyncio
async def test_three_way_missing_dn_blocks_posting(db_session: AsyncSession) -> None:
    """Configured 3-way sales must not silently downgrade when DN is missing."""
    from app.models.invoice import SalesDocumentType

    config = _sales_config()
    so_number = "SO-NO-DN-1"
    so_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="No DN Customer",
        so_reference=so_number,
        invoice_no=so_number,
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.SO.value,
        subtotal=Decimal("100"),
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-SO",
    )
    db_session.add(so_doc)
    await db_session.flush()
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number=so_number,
        customer="No DN Customer",
        so_qty=Decimal("10"),
        so_unit_price=Decimal("10"),
        so_document_id=so_doc.id,
    )
    db_session.add(so)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="No DN Customer",
        so_reference=so_number,
        invoice_no="INV-NO-DN-1",
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.INVOICE.value,
        document_type_code="DT-07",
        subtotal=Decimal("100"),
        total=Decimal("100"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            qty=Decimal("10"),
            unit_price=Decimal("10"),
            amount=Decimal("100"),
        )
    )
    so.invoice_id = inv.id
    await db_session.flush()

    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.blocked is True
    assert gate.outcome is not None
    assert gate.outcome.status == "No DN"
    assert gate.match_mode == "three_way_so_dn"


@pytest.mark.asyncio
async def test_no_grn_not_cleared_by_variance_approval(db_session: AsyncSession) -> None:
    config = _purchase_config()
    po_number = "PO-NO-GRN-APPR-1"
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Still No GRN",
        po_reference=po_number,
        invoice_no=po_number,
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("50"),
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-02",
    )
    db_session.add(po_doc)
    await db_session.flush()
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number=po_number,
        vendor="Still No GRN",
        po_qty=Decimal("5"),
        po_unit_price=Decimal("10"),
        po_document_id=po_doc.id,
        variance_approved=True,
    )
    db_session.add(po)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Still No GRN",
        po_reference=po_number,
        invoice_no="INV-STILL-NO-GRN",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        document_type_code="DT-09",
        subtotal=Decimal("50"),
        total=Decimal("50"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            qty=Decimal("5"),
            unit_price=Decimal("10"),
            amount=Decimal("50"),
        )
    )
    po.invoice_id = inv.id
    await db_session.flush()

    inv = await _reload_invoice(db_session, inv.id)
    gate = await evaluate_match_variance_gate(db_session, inv, config=config)
    assert gate.outcome is not None
    assert gate.outcome.status == "No GRN"
    # Variance approval must not clear a missing-receipt hold.
    assert gate.blocked is True


@pytest.mark.asyncio
async def test_approve_purchase_variance_triggers_resume(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _purchase_config()
    po, inv = await _build_purchase_variance_triplet(db_session)
    await log_event(
        db_session,
        "three_way_match_variance_unapproved",
        invoice_id=inv.id,
        detail={"match_status": "Qty Variance"},
    )
    inv.status = InvoiceStatus.EXCEPTION
    await db_session.flush()

    resume_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.match.match_variance_gate_service.resume_invoice_posting_after_variance_approval",
        resume_mock,
    )

    async def _load_cfg(_session, _tenant_id):
        return config

    monkeypatch.setattr(
        "app.services.purchase.purchase_match_service.load_classification_config",
        _load_cfg,
    )

    await approve_purchase_variance(db_session, TESTING_TENANT_UUID, po.id)
    assert resume_mock.await_count == 1
