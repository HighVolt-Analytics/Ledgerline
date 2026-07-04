
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Invoice routing evaluation tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.models.vendor_master import VendorMasterRecord
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_PENDING_VENDOR,
    ROUTE_PURCHASE,
    apply_invoice_evaluation,
    evaluate_invoice_routing,
    load_config_for_tenant,
    parse_matched_rule_ids,
)
from app.services.rule_book.rule_book_mapper import clear_classification_config_cache


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    clear_classification_config_cache()
    yield
    clear_classification_config_cache()


@pytest.mark.asyncio
async def test_evaluate_invoice_with_po_routes_to_purchase(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
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
    config = await load_config_for_tenant(db_session, TESTING_TENANT_UUID)
    result = evaluate_invoice_routing(loaded, config, mapping_rule_type="Purchase rule")
    assert result.route_target in {ROUTE_PURCHASE, "Purchase Management"}
    assert any(rule.startswith("purchase:") for rule in result.matched_rule_ids)


@pytest.mark.asyncio
async def test_apply_invoice_evaluation_persists_fields(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
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
    assert result.evaluation_status in {EVAL_PENDING_VENDOR, "needs_review"}
    assert inv.evaluation_status in {EVAL_PENDING_VENDOR, "needs_review"}
    assert inv.vendor_confidence == result.vendor_confidence
    assert parse_matched_rule_ids(inv.matched_rule_ids) == result.matched_rule_ids


@pytest.mark.asyncio
async def test_apply_invoice_evaluation_uses_db_vendor_master(db_session: AsyncSession) -> None:
    """Pipeline must not crash or hold when vendor exists in DB but not rule book JSON."""

    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-msft",
            name="Microsoft Pty Ltd",
            abn="29002588189",
            default_ledger="Cloud Hosting Expense",
            status="Active",
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Microsoft Pty Ltd",
        abn="29002588189",
        invoice_no="MSFT-1",
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()

    loaded = (
        await db_session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    config = validate_rule_book_config_payload(
        {
            "vendor_masters": [],
            "vendor_detection_config": {
                "threshold": 80,
                "weights": {"name": 30, "abn": 40, "bank": 20, "address": 10},
            },
        }
    )
    result = await apply_invoice_evaluation(db_session, loaded, config=config)
    assert result.evaluation_status != EVAL_PENDING_VENDOR
    assert inv.evaluation_status != EVAL_PENDING_VENDOR


@pytest.mark.asyncio
async def test_list_invoices_filter_by_route_target(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
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
        tenant_id=TESTING_TENANT_UUID,
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
            tenant_id=TESTING_TENANT_UUID,
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
