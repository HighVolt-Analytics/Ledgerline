"""Tests for purchase dossier (drawer PO Match tab)."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.services.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.purchase_dossier_service import build_purchase_dossier
from app.services.purchase_document_service import sync_purchase_document


@pytest.mark.asyncio
async def test_dossier_without_po_reference(db_session: AsyncSession) -> None:
    inv = Invoice(org_id=1, vendor="Acme", status=InvoiceStatus.MAPPING)
    db_session.add(inv)
    await db_session.flush()

    dossier = await build_purchase_dossier(db_session, inv)
    assert dossier.po_reference is None
    assert all(not member.present for member in dossier.members)
    assert dossier.match is None


@pytest.mark.asyncio
async def test_dossier_po_and_invoice_linked(db_session: AsyncSession) -> None:
    from app.models.line_item import LineItem
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    po_doc = Invoice(
        org_id=1,
        vendor="Meta Platforms Ireland",
        po_reference="PO-MKT-2026-200",
        invoice_no="PO-MKT-2026-200",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("500.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="Widgets",
            qty=Decimal("10"),
            unit_price=Decimal("50"),
            amount=Decimal("500"),
        )
    )
    await db_session.flush()
    await sync_purchase_document(db_session, po_doc)

    commercial = Invoice(
        org_id=1,
        vendor="Meta Platforms Ireland",
        po_reference="PO-MKT-2026-200",
        invoice_no="META-INV-200",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(commercial)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=commercial.id,
            description="Widgets",
            qty=Decimal("10"),
            unit_price=Decimal("50"),
            amount=Decimal("500"),
        )
    )
    await db_session.flush()
    await sync_purchase_document(db_session, commercial)

    commercial = (
        await db_session.execute(
            select(Invoice).where(Invoice.id == commercial.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    dossier = await build_purchase_dossier(db_session, commercial)
    assert dossier.po_reference == "PO-MKT-2026-200"
    by_role = {member.role: member for member in dossier.members}
    assert by_role["po"].present is True
    assert by_role["po"].invoice_id == po_doc.id
    assert by_role["invoice"].present is True
    assert by_role["invoice"].is_current is True
    assert by_role["grn"].present is False
    assert dossier.match is not None
    assert dossier.match_status == "No GRN"
