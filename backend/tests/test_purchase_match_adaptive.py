"""Adaptive purchase match tier resolution."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.services.purchase.purchase_match_service import (
    compute_two_way_grn_match,
    resolve_purchase_match_context,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_resolve_purchase_match_context_three_way(db_session: AsyncSession) -> None:
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-100",
        vendor="Acme",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("50"),
    )
    db_session.add(po)
    await db_session.flush()
    db_session.add(
        GoodsReceipt(
            tenant_id=TESTING_TENANT_UUID,
            purchase_order_id=po.id,
            grn_qty=Decimal("10"),
        )
    )
    await db_session.flush()

    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        po_reference="PO-100",
        invoice_no="INV-1",
        status=InvoiceStatus.VALIDATING,
    )
    ctx = await resolve_purchase_match_context(db_session, invoice)
    assert ctx.effective_mode == "three_way_po_grn"
    assert ctx.po is not None
    assert ctx.grn is not None


@pytest.mark.asyncio
async def test_resolve_purchase_match_context_two_way_po(db_session: AsyncSession) -> None:
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-200",
        vendor="Acme",
        po_qty=Decimal("5"),
        po_unit_price=Decimal("20"),
    )
    db_session.add(po)
    await db_session.flush()

    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        po_reference="PO-200",
        invoice_no="INV-2",
        status=InvoiceStatus.VALIDATING,
    )
    ctx = await resolve_purchase_match_context(db_session, invoice)
    assert ctx.effective_mode == "two_way_po_ses"
    assert ctx.po is not None
    assert ctx.grn is None


@pytest.mark.asyncio
async def test_resolve_purchase_match_context_two_way_grn(db_session: AsyncSession) -> None:
    grn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-3",
        purchase_document_type=PurchaseDocumentType.GRN.value,
        status=InvoiceStatus.MAPPING,
        subtotal=Decimal("100"),
    )
    grn_doc.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=0,
            description="Widgets",
            qty=Decimal("5"),
            unit_price=Decimal("20"),
        )
    ]
    db_session.add(grn_doc)
    await db_session.flush()

    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-3",
        status=InvoiceStatus.VALIDATING,
        subtotal=Decimal("100"),
    )
    invoice.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=0,
            description="Widgets",
            qty=Decimal("5"),
            unit_price=Decimal("20"),
        )
    ]
    ctx = await resolve_purchase_match_context(db_session, invoice)
    assert ctx.effective_mode == "two_way_grn_invoice"
    assert ctx.grn_invoice is not None


@pytest.mark.asyncio
async def test_resolve_purchase_match_context_none(db_session: AsyncSession) -> None:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        invoice_no="INV-ONLY",
        status=InvoiceStatus.VALIDATING,
    )
    ctx = await resolve_purchase_match_context(db_session, invoice)
    assert ctx.effective_mode == "none"


def test_compute_two_way_grn_match_clean() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        subtotal=Decimal("100"),
        total=Decimal("110"),
    )
    inv.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=0,
            description="Item",
            qty=Decimal("5"),
            unit_price=Decimal("20"),
        )
    ]
    match = compute_two_way_grn_match(grn_qty=Decimal("5"), inv=inv)
    assert match.status == "2-Way Match"
