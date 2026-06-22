"""Route-target gating for category coding books → legacy cascade."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.invoice_evaluation_service import ROUTE_PURCHASE, apply_invoice_evaluation
from app.services.rule_book_mapper import FALLBACK_RULE_TYPE, resolve_config_mapping
from app.services.capture_channel import is_staff_claim_sender


def _template_config():
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    return validate_rule_book_config_payload(json.loads(template.read_text(encoding="utf-8")))


def test_aws_purchase_route_uses_purchase_book_only() -> None:
    """AWS + PO-CLOUD on Purchase Management → Book 2, not expense rules."""
    config = _template_config()
    inv = Invoice(
        tenant_id=1,
        vendor="Amazon Web Services",
        abn="63110305305",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target=ROUTE_PURCHASE,
        vendor_confidence=85.0,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    inv.line_items = [
        LineItem(description="AWS EC2 usage", qty=1, unit_price=100, amount=100),
    ]

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == "Purchase rule"
    assert hit.mapping.account_name == "Cloud Hosting Expense"
    assert hit.mapping.account_code == "6110"


def test_telstra_purchase_route_skips_expense_book() -> None:
    """Telstra on Purchase Management must not use expense rule er-3."""
    config = _template_config()
    config.legacy_cascade.vendors["Telstra Corporation"] = "Software Subscription Expense"

    inv = Invoice(
        tenant_id=1,
        vendor="Telstra Corporation",
        abn="33051775556",
        invoice_no="TEL-2026-4410",
        route_target=ROUTE_PURCHASE,
        vendor_confidence=99.0,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type != "Expense rule"
    assert hit.rule_type == "Legacy cascade"
    assert hit.mapping.account_name == "Software Subscription Expense"
    assert "Telstra" in hit.match_reason


def test_expense_route_skips_rules_for_staff_mob_sender() -> None:
    config = _template_config()
    employee = config.employee_masters[0]
    assert is_staff_claim_sender(employee.whatsapp_number, config.employee_masters)

    inv = Invoice(
        tenant_id=1,
        vendor="Telstra Corporation",
        invoice_no="TEL-MOB-1",
        route_target="Expenses Management",
        email_sender=employee.whatsapp_number,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type != "Expense rule"


def test_vault_route_skips_category_books() -> None:
    config = _template_config()
    inv = Invoice(
        tenant_id=1,
        vendor="Amazon Web Services",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target="Vault",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )

    hit = resolve_config_mapping(inv, config)
    assert hit.rule_type == "Legacy cascade"
    assert hit.mapping.account_name == "Cloud Hosting Expense"


@pytest.mark.asyncio
async def test_aws_pipeline_mapping_after_evaluation(db_session: AsyncSession) -> None:
    """End-to-end: evaluated AWS invoice maps via purchase book when routed to Purchase."""
    config = _template_config()
    inv = Invoice(
        tenant_id=1,
        vendor="Amazon Web Services",
        abn="63110305305",
        invoice_no="AWS-AU-204815",
        po_reference="PO-CLOUD-2026-001",
        route_target=ROUTE_PURCHASE,
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
    assert hit.rule_type == "Purchase rule"
    assert hit.mapping.account_code == "6110"


@pytest.mark.asyncio
async def test_telstra_purchase_pipeline_skips_expense_book(db_session: AsyncSession) -> None:
    config = _template_config()
    config.legacy_cascade.vendors["Telstra Corporation"] = "Software Subscription Expense"

    inv = Invoice(
        tenant_id=1,
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
    assert hit.rule_type != "Expense rule"
    assert hit.rule_type == "Legacy cascade"
    assert hit.mapping.account_name == "Software Subscription Expense"
