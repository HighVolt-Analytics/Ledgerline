"""Regression: bulk line-item replace must not break the next ORM query (autoflush)."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.invoice.invoice_data import ParsedLineItem
from app.services.invoice.pipeline import _replace_line_items
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_replace_line_items_then_reload_invoice(db_session) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path="vault/test.pdf",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="old line",
            amount=Decimal("10.00"),
        )
    )
    await db_session.flush()

    stmt = (
        select(Invoice)
        .where(Invoice.id == inv.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await db_session.execute(stmt)).scalar_one()
    assert len(loaded.line_items) == 1

    await _replace_line_items(
        db_session,
        loaded,
        [ParsedLineItem(description="new line", amount=Decimal("20.00"))],
    )

    reloaded = (await db_session.execute(stmt)).scalar_one()
    assert len(reloaded.line_items) == 1
    assert reloaded.line_items[0].description == "new line"
    assert reloaded.line_items[0].amount == Decimal("20.00")
