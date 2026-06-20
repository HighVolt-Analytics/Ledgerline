"""Bundle vendor resolution across PO / GRN / invoice dossiers."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.purchase_order import PurchaseOrder
from app.schemas.rule_book_config import VendorMaster
from app.services.bundle_vendor_service import (
    reconcile_dossier_vendor,
    resolve_canonical_vendor_name,
    vendors_align_to_same_master,
)
from app.services.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.purchase_document_service import sync_purchase_document


def _sysco_master() -> VendorMaster:
    return VendorMaster(
        id="vm-sysco",
        name="Sysco Australia Pty Ltd",
        aliases=["Sysco", "Sysco Foods Australia"],
        abn="12345678901",
    )


def test_resolve_canonical_vendor_prefers_master_abn(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import bundle_vendor_service as mod

    monkeypatch.setattr(
        mod,
        "load_classification_config",
        lambda org_id: type("Cfg", (), {"vendor_masters": [_sysco_master()]})(),
    )
    name = resolve_canonical_vendor_name(
        1,
        vendor_names=["Sysco", "Sysco Food Services"],
        abns=[None, "12345678901"],
    )
    assert name == "Sysco Australia Pty Ltd"


def test_vendors_align_to_same_master_fuzzy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import bundle_vendor_service as mod

    monkeypatch.setattr(
        mod,
        "load_classification_config",
        lambda org_id: type("Cfg", (), {"vendor_masters": [_sysco_master()]})(),
    )
    assert vendors_align_to_same_master(1, "Sysco", None, "Sysco Foods Australia", None)


async def _add_line(session: AsyncSession, inv: Invoice) -> None:
    from app.models.line_item import LineItem

    session.add(
        LineItem(
            invoice_id=inv.id,
            description="Widgets",
            qty=Decimal("10"),
            unit_price=Decimal("50"),
            amount=Decimal("500"),
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_grn_inherits_po_vendor_over_wrong_ocr(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import bundle_vendor_service as mod

    monkeypatch.setattr(
        mod,
        "load_classification_config",
        lambda org_id: type("Cfg", (), {"vendor_masters": [_sysco_master()]})(),
    )

    po_doc = Invoice(
        org_id=1,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-MKT-2026-200",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    await _add_line(db_session, po_doc)
    await sync_purchase_document(db_session, po_doc)

    grn_doc = Invoice(
        org_id=1,
        vendor="Wrong Warehouse Name",
        po_reference="PO-MKT-2026-200",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.GRN.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(grn_doc)
    await db_session.flush()
    await _add_line(db_session, grn_doc)

    po = (
        await db_session.execute(
            select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-MKT-2026-200")
        )
    ).scalar_one()
    await reconcile_dossier_vendor(
        db_session, grn_doc, po, document_type=PurchaseDocumentType.GRN.value
    )
    await db_session.commit()

    assert grn_doc.vendor == "Sysco Australia Pty Ltd"
    refreshed_po = await db_session.get(PurchaseOrder, po.id)
    assert refreshed_po is not None
    assert refreshed_po.vendor == "Sysco Australia Pty Ltd"


@pytest.mark.asyncio
async def test_commercial_invoice_aligns_to_po_master(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import bundle_vendor_service as mod

    monkeypatch.setattr(
        mod,
        "load_classification_config",
        lambda org_id: type("Cfg", (), {"vendor_masters": [_sysco_master()]})(),
    )

    po_doc = Invoice(
        org_id=1,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-MKT-2026-201",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    await _add_line(db_session, po_doc)
    await sync_purchase_document(db_session, po_doc)

    inv = Invoice(
        org_id=1,
        vendor="Sysco",
        po_reference="PO-MKT-2026-201",
        invoice_no="INV-201",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()
    await _add_line(db_session, inv)
    await sync_purchase_document(db_session, inv)
    await db_session.commit()

    assert inv.vendor == "Sysco Australia Pty Ltd"
    po = (
        await db_session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.po_number == "PO-MKT-2026-201")
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalar_one()
    assert po.vendor == "Sysco Australia Pty Ltd"
    assert po.invoice_id == inv.id
