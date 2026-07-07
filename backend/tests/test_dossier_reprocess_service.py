"""Sibling dossier upload triggers reprocess of held commercial invoices."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus, SalesDocumentType
from app.models.line_item import LineItem
from app.services.dossier.dossier_reprocess_service import reprocess_held_commercial_invoices_on_anchor
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_reprocess_held_commercial_on_so_anchor(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    held = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference="SO-500",
        invoice_no="INV-500",
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.INVOICE.value,
        status=InvoiceStatus.EXCEPTION,
        subtotal=Decimal("100"),
        total=Decimal("110"),
        raw_file_path="tenant/hv-org/invoice/held.pdf",
    )
    held.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=0,
            description="Item",
            qty=Decimal("1"),
            amount=Decimal("100"),
        )
    ]
    db_session.add(held)
    await db_session.flush()

    processed: list[int] = []

    async def fake_process(session, inv):
        processed.append(inv.id)

    monkeypatch.setattr(
        "app.services.invoice.pipeline.process_invoice",
        fake_process,
    )

    ids = await reprocess_held_commercial_invoices_on_anchor(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_SALES,
        anchor_ref="SO-500",
        triggering_invoice_id=999,
    )
    assert held.id in ids
    assert held.id in processed
    assert held.status == InvoiceStatus.PENDING
