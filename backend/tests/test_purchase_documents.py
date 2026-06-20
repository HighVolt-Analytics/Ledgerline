"""PO-first purchase documents (Option A)."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.purchase_order import PurchaseOrder
from app.services.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.purchase_document_service import (
    EVAL_AWAITING_PO,
    infer_purchase_document_type,
    sync_purchase_document,
)


def test_infer_po_from_filename_not_subject() -> None:
    inv = Invoice(
        email_subject="po",
        email_attachment_name="test-po-PO-MKT-2026-TEST.pdf",
        po_reference="PO-MKT-2026-TEST",
        total=Decimal("500.00"),
    )
    assert infer_purchase_document_type(inv) == PurchaseDocumentType.PO.value


def test_infer_grn_from_attachment_not_subject() -> None:
    inv = Invoice(
        email_subject="gr",
        email_attachment_name="test-grn-PO-MKT-2026-TEST.pdf",
        po_reference="PO-MKT-2026-014",
    )
    assert infer_purchase_document_type(inv) == PurchaseDocumentType.GRN.value


def test_infer_commercial_invoice_from_filename() -> None:
    inv = Invoice(
        email_subject="fwd",
        email_attachment_name="test-invoice-PO-MKT-2026-TEST.pdf",
        po_reference="PO-MKT-2026-014",
        invoice_no="INV-MKT-TEST-001",
    )
    assert infer_purchase_document_type(inv) == PurchaseDocumentType.INVOICE.value


def test_infer_po_from_parsed_fields_when_filename_generic() -> None:
    inv = Invoice(
        email_attachment_name="document.pdf",
        po_reference="PO-MKT-2026-TEST",
        total=Decimal("500.00"),
    )
    assert infer_purchase_document_type(inv) == PurchaseDocumentType.PO.value


def test_infer_po_from_document_heading_when_due_date_present() -> None:
    inv = Invoice(
        email_attachment_name="document.pdf",
        document_text="Acme Corp PURCHASE ORDER\nNo: PO-2025-00142\nDue: 30 Jun 2025",
        due_date=__import__("datetime").date(2025, 6, 30),
        total=Decimal("261370.00"),
    )
    assert infer_purchase_document_type(inv) == PurchaseDocumentType.PO.value


def test_infer_grn_from_document_heading() -> None:
    inv = Invoice(
        email_attachment_name="scan.pdf",
        document_text="GOODS RECEIPT NOTE\nGRN-2025-00089",
    )
    assert infer_purchase_document_type(inv) == PurchaseDocumentType.GRN.value


def test_infer_invoice_from_parsed_invoice_number() -> None:
    inv = Invoice(
        email_attachment_name="scan.pdf",
        po_reference="PO-MKT-2026-014",
        invoice_no="INV-MKT-TEST-001",
        due_date=__import__("datetime").date(2026, 7, 11),
    )
    assert infer_purchase_document_type(inv) == PurchaseDocumentType.INVOICE.value


async def _add_line(session: AsyncSession, inv: Invoice, qty: str = "10", price: str = "50") -> Invoice:
    from app.models.line_item import LineItem

    session.add(
        LineItem(
            invoice_id=inv.id,
            description="Widgets",
            qty=Decimal(qty),
            unit_price=Decimal(price),
            amount=Decimal(qty) * Decimal(price),
        )
    )
    await session.flush()
    return (
        await session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_po_first_then_commercial_invoice(db_session: AsyncSession) -> None:
    po_doc = Invoice(
        org_id=1,
        vendor="Meta Platforms Ireland",
        po_reference="PO-MKT-2026-100",
        invoice_no="PO-MKT-2026-100",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("500.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    await _add_line(db_session, po_doc, "10", "50")

    po_row = await sync_purchase_document(db_session, po_doc)
    assert po_row is not None
    assert po_row.po_number == "PO-MKT-2026-100"
    assert po_row.po_document_id == po_doc.id
    assert po_row.invoice_id is None

    commercial = Invoice(
        org_id=1,
        vendor="Meta Platforms Ireland",
        po_reference="PO-MKT-2026-100",
        invoice_no="META-INV-100",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(commercial)
    await db_session.flush()
    await _add_line(db_session, commercial, "10", "50")

    linked = await sync_purchase_document(db_session, commercial)
    assert linked is not None
    assert linked.invoice_id == commercial.id
    assert linked.po_document_id == po_doc.id


@pytest.mark.asyncio
async def test_commercial_invoice_awaiting_po(db_session: AsyncSession) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Meta Platforms Ireland",
        po_reference="PO-MKT-2026-999",
        invoice_no="META-INV-999",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("100.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()
    await _add_line(db_session, inv)

    result = await sync_purchase_document(db_session, inv)
    assert result is None
    assert inv.evaluation_status == EVAL_AWAITING_PO
    assert inv.status == InvoiceStatus.EXCEPTION

    po_count = (
        await db_session.execute(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-MKT-2026-999"))
    ).scalar_one_or_none()
    assert po_count is None
