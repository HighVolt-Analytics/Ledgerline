"""Document-type Post to GL mapping (replaces route-specific GL rule books)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, apply_invoice_evaluation
from app.services.rule_book.rule_book_mapper import (
    DOCUMENT_TYPE_RULE_TYPE,
    FALLBACK_RULE_TYPE,
    resolve_config_mapping,
)
from app.services.ingest.capture_channel import is_staff_claim_sender
from app.tenant_ids import TESTING_TENANT_UUID
from tests.rule_book_fixtures import load_capture_config


def _template_config():
    return load_capture_config()


def test_aws_document_type_maps_cloud_hosting() -> None:
    """PO goods invoice (DT-01) maps via Post to, not purchase GL rules."""
    config = _template_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        abn="63110305305",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target=ROUTE_PURCHASE,
        document_type_code="DT-01",
        vendor_confidence=85.0,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    inv.line_items = [
        LineItem(description="AWS EC2 usage", qty=1, unit_price=100, amount=100),
    ]

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert hit.mapping.account_name == "Cloud Hosting Expense"
    assert hit.mapping.account_code == "6110"


def test_unclassified_purchase_invoice_uses_fallback() -> None:
    """Invoices without a document type fall back to posting defaults."""
    config = _template_config()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Telstra Corporation",
        abn="33051775556",
        invoice_no="TEL-2026-4410",
        route_target=ROUTE_PURCHASE,
        vendor_confidence=99.0,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == FALLBACK_RULE_TYPE
    assert hit.mapping.account_name == "Suspense Account"


def test_expense_route_without_document_type_uses_fallback() -> None:
    config = _template_config()
    employee = config.employee_masters[0]
    assert is_staff_claim_sender(employee.whatsapp_number, config.employee_masters)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Telstra Corporation",
        invoice_no="TEL-MOB-1",
        route_target="Expenses Management",
        email_sender=employee.whatsapp_number,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == FALLBACK_RULE_TYPE
    assert hit.rule_type != "Expense rule"


def test_vault_route_without_document_type_uses_fallback() -> None:
    config = _template_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target="Vault",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == FALLBACK_RULE_TYPE


@pytest.mark.asyncio
async def test_aws_pipeline_mapping_after_evaluation(db_session: AsyncSession) -> None:
    """Evaluated AWS invoice with DT-01 maps via document-type Post to."""
    config = _template_config()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        abn="63110305305",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target=ROUTE_PURCHASE,
        document_type_code="DT-01",
        vendor_confidence=85.0,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="aws-route-gate-1",
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
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await apply_invoice_evaluation(db_session, loaded, config=config, enqueue_pending=False)

    hit = resolve_config_mapping(loaded, config)
    assert loaded.route_target == ROUTE_PURCHASE
    assert hit.rule_type == DOCUMENT_TYPE_RULE_TYPE
    assert hit.mapping.account_code == "6110"


@pytest.mark.asyncio
async def test_telstra_purchase_without_document_type_falls_back(db_session: AsyncSession) -> None:
    config = _template_config()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Telstra Corporation",
        abn="33051775556",
        invoice_no="TEL-2026-4410",
        route_target=ROUTE_PURCHASE,
        vendor_confidence=99.0,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="telstra-route-gate-1",
    )
    db_session.add(inv)
    await db_session.flush()

    loaded = (
        await db_session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await apply_invoice_evaluation(db_session, loaded, config=config, enqueue_pending=False)

    hit = resolve_config_mapping(loaded, config)
    assert hit.rule_type == FALLBACK_RULE_TYPE
    assert hit.mapping.account_name == "Suspense Account"
