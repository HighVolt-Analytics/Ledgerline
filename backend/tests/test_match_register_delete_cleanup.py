"""Permanent delete removes purchase/sales match-register orphans."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.models.delivery_note import DeliveryNote
from app.tenant_ids import TESTING_TENANT_UUID

_TID = str(TESTING_TENANT_UUID).replace("-", "")
_TENANT_PREFIX = f"tenants/{_TID}"


@pytest.mark.asyncio
async def test_permanent_delete_removes_orphan_purchase_register(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / _TENANT_PREFIX / "rejected" / "HvOrg" / "Acme" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "PO-DEL_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="PO-DEL",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="po-del-hash",
        raw_file_path=str(pdf),
        total=Decimal("100"),
        route_target="Purchase Management",
        purchase_document_type="po",
        po_reference="PO-DEL-1",
    )
    db_session.add(po_doc)
    await db_session.flush()

    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-DEL-1",
        vendor="Acme",
        po_qty=Decimal("1"),
        po_unit_price=Decimal("100"),
        po_document_id=po_doc.id,
    )
    db_session.add(po)
    await db_session.flush()

    before = await client.get("/api/purchases")
    assert before.status_code == 200
    assert any(row["po_number"] == "PO-DEL-1" for row in before.json()["data"])

    res = await client.delete(f"/api/approvals/{po_doc.id}")
    assert res.status_code == 204

    leftover = (
        await db_session.execute(
            select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-DEL-1")
        )
    ).scalar_one_or_none()
    assert leftover is None

    after = await client.get("/api/purchases")
    assert after.status_code == 200
    assert all(row["po_number"] != "PO-DEL-1" for row in after.json()["data"])


@pytest.mark.asyncio
async def test_permanent_delete_removes_grn_and_prunes_orphan_po(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / _TENANT_PREFIX / "rejected" / "HvOrg" / "Acme" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "GRN-DEL_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    grn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="GRN-DEL",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="grn-del-hash",
        raw_file_path=str(pdf),
        total=Decimal("50"),
        route_target="Purchase Management",
        purchase_document_type="grn",
        po_reference="PO-GRN-ONLY",
    )
    db_session.add(grn_doc)
    await db_session.flush()

    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-GRN-ONLY",
        vendor="Acme",
        po_qty=Decimal("1"),
        po_unit_price=Decimal("50"),
    )
    db_session.add(po)
    await db_session.flush()

    grn = GoodsReceipt(
        tenant_id=TESTING_TENANT_UUID,
        purchase_order_id=po.id,
        grn_qty=Decimal("1"),
        grn_invoice_id=grn_doc.id,
    )
    db_session.add(grn)
    await db_session.flush()

    res = await client.delete(f"/api/approvals/{grn_doc.id}")
    assert res.status_code == 204

    assert (
        await db_session.execute(
            select(GoodsReceipt).where(GoodsReceipt.grn_invoice_id == grn_doc.id)
        )
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(
            select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-GRN-ONLY")
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_permanent_delete_removes_orphan_sales_register(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / _TENANT_PREFIX / "rejected" / "HvOrg" / "Cust" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "SO-DEL_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    so_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Cust",
        invoice_no="SO-DEL",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="so-del-hash",
        raw_file_path=str(pdf),
        total=Decimal("200"),
        route_target="Sales Management",
        sales_document_type="so",
        so_reference="SO-DEL-1",
    )
    db_session.add(so_doc)
    await db_session.flush()

    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number="SO-DEL-1",
        customer="Cust",
        so_qty=Decimal("1"),
        so_unit_price=Decimal("200"),
        so_document_id=so_doc.id,
    )
    db_session.add(so)
    await db_session.flush()

    dn = DeliveryNote(
        tenant_id=TESTING_TENANT_UUID,
        sales_order_id=so.id,
        dn_qty=Decimal("1"),
    )
    db_session.add(dn)
    await db_session.flush()

    res = await client.delete(f"/api/approvals/{so_doc.id}")
    assert res.status_code == 204

    assert (
        await db_session.execute(
            select(SalesOrder).where(SalesOrder.so_number == "SO-DEL-1")
        )
    ).scalar_one_or_none() is None

    after = await client.get("/api/sales")
    assert after.status_code == 200
    assert all(row["so_number"] != "SO-DEL-1" for row in after.json()["data"])


@pytest.mark.asyncio
async def test_route_target_list_hides_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Team Co",
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="team-rej-hash",
        route_target="Team Expenses",
        total=Decimal("25"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/invoices", params={"route_target": "Team Expenses"})
    assert res.status_code == 200
    assert all(row["id"] != inv.id for row in res.json()["data"])
