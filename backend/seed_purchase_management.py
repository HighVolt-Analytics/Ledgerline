"""Seed demo purchase orders for /purchases three-way match UI testing.

Run from backend/:
    python seed_purchase_management.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.services.shared.file_storage import store_invoice_pdf
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.org_context import get_or_create_default_org
from app.services.purchase.purchase_match_service import (
    compute_three_way_match,
    record_goods_receipt,
    sync_purchase_order_from_invoice,
    _derive_status,
)
from app.schemas.purchase import GoodsReceiptCreate

DEMO_HASH_PREFIX = "purchase_demo_"
_MIN_PDF = b"%PDF-1.4 purchase-demo"


async def _add_invoice(
    session,
    org,
    *,
    hash_suffix: str,
    po_number: str,
    vendor: str,
    invoice_no: str,
    qty: Decimal,
    unit_price: Decimal,
    status: InvoiceStatus,
    matched_rule_ids: list[str] | None = None,
) -> Invoice:
    subtotal = qty * unit_price
    gst = (subtotal * Decimal("0.10")).quantize(Decimal("0.01"))
    total = subtotal + gst
    inv_date = date.today()

    inv = Invoice(
        org_id=org.id,
        vendor=vendor,
        invoice_no=invoice_no,
        po_reference=po_number,
        invoice_date=inv_date,
        currency="AUD",
        subtotal=subtotal,
        gst=gst,
        total=total,
        status=status,
        file_hash=f"{DEMO_HASH_PREFIX}{hash_suffix}",
        email_sender="accounts@supplier.com",
        route_target=ROUTE_PURCHASE,
        evaluation_status="auto_coded",
        matched_rule_ids=json.dumps(matched_rule_ids or ["purchase:pr-1"]),
        account_name="Purchase Management",
    )
    session.add(inv)
    await session.flush()

    stored = store_invoice_pdf(
        _MIN_PDF,
        org.slug,
        vendor.lower().replace(" ", "-")[:50],
        inv.id,
        inv.file_hash or "",
        f"{invoice_no}.pdf",
        org_name=org.name,
        vendor_name=vendor,
        invoice_no=invoice_no,
        invoice_date=inv_date,
    )
    inv.raw_file_path = stored

    session.add(
        LineItem(
            invoice_id=inv.id,
            description=f"{vendor} — line item",
            qty=qty,
            unit_price=unit_price,
            amount=subtotal,
        )
    )
    await session.flush()
    return inv


async def seed_purchase_management() -> None:
    async with async_session_factory() as session:
        org = await get_or_create_default_org(session)
        existing = (
            await session.execute(
                select(Invoice).where(
                    Invoice.org_id == org.id,
                    Invoice.file_hash.like(f"{DEMO_HASH_PREFIX}%"),
                )
            )
        ).scalars().first()
        if existing:
            print("Purchase demo data already exists — skipping.")
            return

        # 1. No GRN
        inv1 = await _add_invoice(
            session,
            org,
            hash_suffix="001",
            po_number="PO-DEMO-1001",
            vendor="Sysco Foods",
            invoice_no="INV-PO-1001",
            qty=Decimal("10"),
            unit_price=Decimal("50.00"),
            status=InvoiceStatus.PROCESSED,
        )
        await sync_purchase_order_from_invoice(session, inv1)

        # 2. Three-way match (GRN matches invoice)
        inv2 = await _add_invoice(
            session,
            org,
            hash_suffix="002",
            po_number="PO-DEMO-1002",
            vendor="Bidfood",
            invoice_no="INV-PO-1002",
            qty=Decimal("8"),
            unit_price=Decimal("75.00"),
            status=InvoiceStatus.PROCESSED,
        )
        po2 = await sync_purchase_order_from_invoice(session, inv2)
        assert po2 is not None
        await record_goods_receipt(
            session,
            org.id,
            po2.id,
            GoodsReceiptCreate(
                grn_qty=Decimal("8"),
                grn_date=date.today(),
                receiver="Warehouse A",
                condition_note="Good",
            ),
        )

        # 3. Quantity variance (GRN short)
        inv3 = await _add_invoice(
            session,
            org,
            hash_suffix="003",
            po_number="PO-DEMO-1003",
            vendor="PFD Foods",
            invoice_no="INV-PO-1003",
            qty=Decimal("12"),
            unit_price=Decimal("40.00"),
            status=InvoiceStatus.PROCESSED,
        )
        po3 = await sync_purchase_order_from_invoice(session, inv3)
        assert po3 is not None
        await record_goods_receipt(
            session,
            org.id,
            po3.id,
            GoodsReceiptCreate(
                grn_qty=Decimal("10"),
                grn_date=date.today() - timedelta(days=1),
                receiver="Site B",
                condition_note="Partial delivery",
            ),
        )

        # 4. Price variance (PO unit price lower than invoice)
        inv4 = await _add_invoice(
            session,
            org,
            hash_suffix="004",
            po_number="PO-DEMO-1004",
            vendor="Officeworks",
            invoice_no="INV-PO-1004",
            qty=Decimal("5"),
            unit_price=Decimal("120.00"),
            status=InvoiceStatus.PROCESSED,
        )
        po4 = await sync_purchase_order_from_invoice(session, inv4)
        assert po4 is not None
        po4.po_unit_price = Decimal("100.00")
        await session.flush()
        await record_goods_receipt(
            session,
            org.id,
            po4.id,
            GoodsReceiptCreate(
                grn_qty=Decimal("5"),
                grn_date=date.today(),
                receiver="Procurement",
                condition_note="Good",
            ),
        )
        loaded_inv = await session.get(Invoice, inv4.id)
        if loaded_inv and po4:
            match = compute_three_way_match(po4, loaded_inv)
            po4.status = _derive_status(match, po4)

        for inv in (inv1, inv2, inv3, inv4):
            session.add(
                AuditLog(
                    org_id=org.id,
                    event="purchase_demo_seeded",
                    invoice_id=inv.id,
                    detail={"route_target": ROUTE_PURCHASE},
                )
            )

        await session.commit()
        pos = (
            await session.execute(
                select(PurchaseOrder).where(PurchaseOrder.org_id == org.id)
            )
        ).scalars().all()
        print(f"Seeded {len(pos)} purchase demo POs. Refresh /purchases to review three-way match.")


if __name__ == "__main__":
    asyncio.run(seed_purchase_management())
