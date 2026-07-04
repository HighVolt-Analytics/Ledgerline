"""DT-01 end-to-end: upload PO → GRN → commercial invoice through the live pipeline."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.services.invoice.pipeline import process_invoice
from app.services.reconciliation.reconciliation_service import ReconciliationResult
from app.services.rule_book.validator import ValidationResult
from tests.pipeline_test_helpers import patch_confidence_gate_pass

ASSETS = Path(__file__).resolve().parents[2] / "test-assets"
PO_FILE = ASSETS / "test-po-PO-MKT-2026-TEST.pdf"
GRN_FILE = ASSETS / "test-grn-PO-MKT-2026-TEST.pdf"
INV_FILE = ASSETS / "test-invoice-PO-MKT-2026-TEST.pdf"
PO_NUMBER = "PO-MKT-2026-TEST"


async def _run_pipeline(
    db_session: AsyncSession,
    invoice_id: int,
    *,
    attempts: int = 5,
) -> Invoice:
    terminal = {
        InvoiceStatus.PROCESSED,
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
    inv = await db_session.get(Invoice, invoice_id)
    assert inv is not None
    for _ in range(attempts):
        if inv.status in terminal:
            break
        await process_invoice(db_session, inv)
        await db_session.commit()
        await db_session.refresh(inv)
    return inv


async def _upload(
    client: AsyncClient,
    path: Path,
    *,
    purchase_document_type: str | None = None,
) -> int:
    params = {}
    if purchase_document_type:
        params["purchase_document_type"] = purchase_document_type
    with path.open("rb") as handle:
        res = await client.post(
            "/api/invoices/upload",
            params=params,
            files={"file": (path.name, handle, "application/pdf")},
        )
    assert res.status_code == 200, res.text
    return int(res.json()["data"]["id"])


def _validation_summary(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


@pytest.mark.asyncio
async def test_dt01_po_grn_invoice_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "true")
    get_settings.cache_clear()

    ocr_text = (
        "PURCHASE ORDER PO-MKT-2026-TEST Sysco Foods Australia Pty Ltd "
        "TAX INVOICE goods received note GRN total $550.00 GST included "
        "sufficient OCR text length for image quality gate and classification"
    )

    @contextmanager
    def _fake_open(path: str, **_kwargs):
        for candidate in (PO_FILE, GRN_FILE, INV_FILE):
            if candidate.name in path or str(candidate) in path:
                yield str(candidate)
                return
        yield path

    async def _fake_ocr_read(_path: str, **_kwargs) -> OcrArtifact:
        return OcrArtifact(
            success=True,
            sparse=False,
            text=ocr_text,
            text_length=len(ocr_text),
            di_model="test",
        )

    def _llm_result(*, file_path: str | None = None) -> LlmDocumentResult:
        path = (file_path or "").lower()
        common = dict(
            suggested_dt="DT-01",
            confidence=0.95,
            reasoning="DT-01 purchase document",
            perspective="purchase",
            vendor="Sysco Foods Australia Pty Ltd",
            po_reference=PO_NUMBER,
            seller=LlmParty(name="Sysco Foods Australia Pty Ltd"),
        )
        if "grn" in path:
            return LlmDocumentResult(**common, total="500.00")
        if "test-po" in path or "po_" in path:
            return LlmDocumentResult(**common, total="500.00")
        return LlmDocumentResult(
            **common,
            total="550.00",
            gst="50.00",
            invoice_no="INV-003",
        )

    async def _fake_classify(_ocr, *, file_path=None, **_kwargs) -> LlmDocumentResult:
        return _llm_result(file_path=str(file_path) if file_path else None)

    async def _fake_extract(*_args, **_kwargs) -> LlmDocumentResult:
        file_path = _kwargs.get("file_path")
        if file_path is None and _args:
            file_path = _args[0] if isinstance(_args[0], str) else None
        return _llm_result(file_path=str(file_path) if file_path else None)

    async def _noop_sync(*_args, **_kwargs) -> None:
        return None

    async def _passing_validations(*_args, **_kwargs):
        return [ValidationResult(rule="VR01", passed=True, message="ok", skipped=False)]

    async def _no_vendor_hold(_session, _inv) -> bool:
        return False

    async def _balanced_recon(*_args, **_kwargs) -> ReconciliationResult:
        return ReconciliationResult(
            date=date.today(),
            total_invoices=1,
            total_ap_credits=Decimal("550"),
            total_debits=Decimal("550"),
            total_credits=Decimal("550"),
            rc1_passed=True,
            rc2_passed=True,
            is_balanced=True,
            halted=False,
            halt_reason=None,
        )

    patch_confidence_gate_pass(monkeypatch, dt="DT-01", confidence=0.95)
    monkeypatch.setattr("app.services.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice_pipeline_phases.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.read_for_classification",
        _fake_ocr_read,
    )
    monkeypatch.setattr(
        "app.services.invoice_pipeline_phases.classify_only",
        _fake_classify,
    )
    monkeypatch.setattr("app.services.pipeline.extract_fields", _fake_extract)
    monkeypatch.setattr("app.services.pipeline.sync_invoice_blob_path", _noop_sync)
    monkeypatch.setattr("app.services.pipeline.run_all_validations", _passing_validations)
    monkeypatch.setattr("app.services.pipeline.reconcile_daily", _balanced_recon)
    monkeypatch.setattr(
        "app.services.vendor_hold_service.apply_vendor_hold_if_needed",
        _no_vendor_hold,
    )

    for path in (PO_FILE, GRN_FILE, INV_FILE):
        assert path.is_file(), f"missing test asset: {path}"

    po_id = await _upload(client, PO_FILE, purchase_document_type="po")
    po_doc = await _run_pipeline(db_session, po_id)

    grn_id = await _upload(client, GRN_FILE, purchase_document_type="grn")
    grn_doc = await _run_pipeline(db_session, grn_id)

    inv_id = await _upload(client, INV_FILE, purchase_document_type="invoice")
    inv = await _run_pipeline(db_session, inv_id)

    po_row = (
        await db_session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.tenant_id == inv.tenant_id,
                PurchaseOrder.po_number == PO_NUMBER,
            )
        )
    ).scalar_one_or_none()

    inv = (
        await db_session.execute(
            select(Invoice)
            .where(Invoice.id == inv_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    print("\n--- DT-01 E2E RESULT ---")
    print(f"PO doc id={po_id} status={po_doc.status.value}")
    print(f"GRN doc id={grn_id} status={grn_doc.status.value}")
    print(f"Invoice id={inv_id}")
    print(f"document_type_code={inv.document_type_code!r}")
    print(f"route_target={inv.route_target!r}")
    print(f"status={inv.status.value}")
    print(f"evaluation_status={inv.evaluation_status!r}")
    print(f"account={inv.account_code} {inv.account_name}")
    for row in _validation_summary(inv.validation_results):
        mark = "PASS" if row.get("passed") else "FAIL"
        if row.get("skipped"):
            mark = "SKIP"
        print(f"  {row.get('rule')}: {mark} — {row.get('message')}")
    if po_row:
        print(f"PO register: status={po_row.status.value} match={po_row.three_way_match_status!r}")

    assert inv.document_type_code == "DT-01"
    assert inv.route_target == "Purchase Management"
    assert po_row is not None
    assert po_row.po_document_id == po_id
    assert po_row.invoice_id == inv_id

    failed = [
        r
        for r in _validation_summary(inv.validation_results)
        if not r.get("skipped") and not r.get("passed")
    ]
    assert not failed, f"validation failures: {failed}"
    assert inv.status == InvoiceStatus.PROCESSED, (
        f"expected processed, got {inv.status.value}; validations above"
    )
