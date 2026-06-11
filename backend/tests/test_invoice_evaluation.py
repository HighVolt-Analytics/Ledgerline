"""Invoice routing evaluation tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_PENDING_VENDOR,
    ROUTE_PURCHASE,
    apply_invoice_evaluation,
    evaluate_invoice_routing,
    load_config_for_org,
    parse_matched_rule_ids,
)
from app.services.rule_book_mapper import clear_classification_config_cache


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    clear_classification_config_cache()
    yield
    clear_classification_config_cache()


@pytest.mark.asyncio
async def test_evaluate_invoice_with_po_routes_to_purchase(db_session: AsyncSession) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="EC2 Compute",
            qty=1,
            unit_price=100,
            amount=100,
        )
    )
    await db_session.flush()

    loaded = (
        await db_session.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    config = load_config_for_org(1)
    result = evaluate_invoice_routing(loaded, config, mapping_rule_type="Purchase rule")
    assert result.route_target in {ROUTE_PURCHASE, "Purchase Management"}
    assert any(rule.startswith("purchase:") for rule in result.matched_rule_ids)


@pytest.mark.asyncio
async def test_apply_invoice_evaluation_persists_fields(db_session: AsyncSession) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Unknown Florist Co",
        invoice_no="UNKNOWN-001",
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()

    loaded = (
        await db_session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    result = await apply_invoice_evaluation(db_session, loaded)
    assert result.evaluation_status == EVAL_PENDING_VENDOR
    assert inv.evaluation_status == EVAL_PENDING_VENDOR
    assert inv.vendor_confidence is not None
    assert parse_matched_rule_ids(inv.matched_rule_ids) == result.matched_rule_ids


@pytest.mark.asyncio
async def test_list_invoices_filter_by_route_target(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Sysco Australia",
        invoice_no="SYSCO-INV-88210",
        po_reference="PO-BEV-2026-014",
        status=InvoiceStatus.PROCESSED,
        route_target="Purchase Management",
        evaluation_status=EVAL_AUTO_CODED,
        vendor_confidence=85.0,
        matched_rule_ids='["purchase:pr-001"]',
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/invoices", params={"route_target": "Purchase Management"})
    assert res.status_code == 200
    ids = [row["id"] for row in res.json()["data"]]
    assert inv.id in ids


@pytest.mark.asyncio
async def test_remap_updates_evaluation_fields(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        status=InvoiceStatus.PROCESSED,
        account_code="5000",
        account_name="Cloud Hosting Expense",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="EC2",
            qty=1,
            unit_price=100,
            amount=100,
        )
    )
    await db_session.flush()

    res = await client.post("/api/invoices/remap")
    assert res.status_code == 200

    await db_session.refresh(inv)
    assert inv.route_target is not None
    assert inv.evaluation_status in {EVAL_AUTO_CODED, "needs_review", EVAL_PENDING_VENDOR, "awaiting_po"}
