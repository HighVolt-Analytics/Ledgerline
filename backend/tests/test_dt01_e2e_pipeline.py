"""DT-01 end-to-end: upload PO → GRN → commercial invoice through the live pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.services.pipeline import process_invoice

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
                PurchaseOrder.org_id == inv.org_id,
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
