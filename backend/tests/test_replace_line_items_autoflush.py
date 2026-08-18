"""Regression: bulk line-item replace must not break the next ORM query (autoflush)."""

from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice.pipeline import (
    _apply_parsed_to_invoice,
    _invoice_has_persisted_line_items,
    _replace_line_items,
)
from app.tenant_child_tables import line_items_for_invoice
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


async def _seed_invoice_with_line(db_session, *, description: str = "old line") -> Invoice:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        vendor="Bolos",
        total=Decimal("59.00"),
        raw_file_path="vault/bolos.png",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description=description,
            amount=Decimal("59.00"),
        )
    )
    await db_session.flush()
    return inv


@pytest.mark.asyncio
async def test_has_persisted_line_items_after_expire_does_not_lazy_load(
    db_session,
) -> None:
    inv = await _seed_invoice_with_line(db_session)
    db_session.expire(inv, ["line_items"])

    assert await _invoice_has_persisted_line_items(db_session, inv) is True

    await db_session.execute(
        delete(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id))
    )
    db_session.expire(inv, ["line_items"])
    assert await _invoice_has_persisted_line_items(db_session, inv) is False


@pytest.mark.asyncio
async def test_apply_parsed_preserve_existing_after_stale_line_expire(
    db_session,
) -> None:
    """Understood-path reprocess: stale lines deleted + expired, then persist.

    Staging inv-1260 hit MissingGreenlet on ``if not loaded.line_items`` after
    clear_stale expired the collection and clerk-complete fields set preserve.
    """
    inv = await _seed_invoice_with_line(db_session)
    await db_session.execute(
        delete(LineItem).where(*line_items_for_invoice(inv.tenant_id, inv.id))
    )
    db_session.expire(inv, ["line_items"])

    parsed = InvoiceData(
        vendor="Bolos",
        total=Decimal("59.00"),
        line_items=[ParsedLineItem(description="meal", amount=Decimal("59.00"))],
    )
    await _apply_parsed_to_invoice(
        db_session,
        invoice=inv,
        loaded=inv,
        parsed=parsed,
        config=RuleBookConfigPayload(document_types=[]),
        preserve_existing=True,
    )

    await db_session.refresh(inv, attribute_names=["line_items"])
    assert len(inv.line_items) == 1
    assert inv.line_items[0].description == "meal"
    assert inv.line_items[0].amount == Decimal("59.00")


@pytest.mark.asyncio
async def test_apply_parsed_preserve_existing_keeps_existing_lines(
    db_session,
) -> None:
    inv = await _seed_invoice_with_line(db_session, description="clerk line")
    stmt = (
        select(Invoice)
        .where(Invoice.id == inv.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await db_session.execute(stmt)).scalar_one()

    parsed = InvoiceData(
        vendor="Bolos",
        total=Decimal("59.00"),
        line_items=[ParsedLineItem(description="ocr line", amount=Decimal("10.00"))],
    )
    await _apply_parsed_to_invoice(
        db_session,
        invoice=loaded,
        loaded=loaded,
        parsed=parsed,
        config=RuleBookConfigPayload(document_types=[]),
        preserve_existing=True,
    )

    await db_session.refresh(loaded, attribute_names=["line_items"])
    assert len(loaded.line_items) == 1
    assert loaded.line_items[0].description == "clerk line"


@pytest.mark.asyncio
async def test_apply_parsed_preserve_existing_expired_keeps_db_lines(
    db_session,
) -> None:
    inv = await _seed_invoice_with_line(db_session, description="clerk line")
    db_session.expire(inv, ["line_items"])

    parsed = InvoiceData(
        vendor="Bolos",
        total=Decimal("59.00"),
        line_items=[ParsedLineItem(description="ocr line", amount=Decimal("10.00"))],
    )
    await _apply_parsed_to_invoice(
        db_session,
        invoice=inv,
        loaded=inv,
        parsed=parsed,
        config=RuleBookConfigPayload(document_types=[]),
        preserve_existing=True,
    )

    await db_session.refresh(inv, attribute_names=["line_items"])
    assert len(inv.line_items) == 1
    assert inv.line_items[0].description == "clerk line"


@pytest.mark.asyncio
async def test_apply_parsed_preserve_existing_keeps_clerk_total(
    db_session,
) -> None:
    inv = await _seed_invoice_with_line(db_session, description="clerk line")
    inv.total = Decimal("16000.00")
    inv.extracted_fields = {"total": "16000.00"}
    await db_session.flush()
    stmt = (
        select(Invoice)
        .where(Invoice.id == inv.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await db_session.execute(stmt)).scalar_one()

    parsed = InvoiceData(
        vendor="Classic Enterprise",
        total=Decimal("0"),
        extracted_fields={"total": "0.0"},
        line_items=[ParsedLineItem(description="ocr line", amount=Decimal("0"))],
    )
    await _apply_parsed_to_invoice(
        db_session,
        invoice=loaded,
        loaded=loaded,
        parsed=parsed,
        config=RuleBookConfigPayload(document_types=[]),
        preserve_existing=True,
    )

    assert loaded.total == Decimal("16000.00")
    assert (loaded.extracted_fields or {}).get("total") == "16000.00"

