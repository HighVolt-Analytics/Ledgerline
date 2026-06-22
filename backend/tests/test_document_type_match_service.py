"""Tests for document-type match executors."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.models.line_item import LineItem
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_match_service import (
    compute_two_way_po_match,
    execute_document_match,
    is_clean_match_message,
    resolve_match_mode,
    _extract_reference_invoice_numbers,
)
from app.services.invoice_data import InvoiceData, ParsedLineItem


def _invoice(**kwargs) -> Invoice:
    base = dict(
        id=10,
        tenant_id=1,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        po_reference="PO-100",
        invoice_no="INV-NEW",
        subtotal=Decimal("100.00"),
        total=Decimal("110.00"),
        line_items=[LineItem(description="Service", qty=Decimal("1"), amount=Decimal("100"))],
    )
    base.update(kwargs)
    return Invoice(**base)


def _po(**kwargs) -> PurchaseOrder:
    base = dict(
        id=1,
        tenant_id=1,
        po_number="PO-100",
        po_qty=Decimal("2"),
        po_unit_price=Decimal("50.00"),
        variance_approved=False,
        goods_receipts=[],
    )
    base.update(kwargs)
    return PurchaseOrder(**base)


def test_resolve_match_mode_from_definition() -> None:
    definition = DocumentTypeDefinition(
        code="DT-02",
        title="Services",
        shortTitle="Services",
        klass="Transactional",
        posting="Yes",
        fraudRisk="low",
        oneLine="test",
        routeTarget="Purchase Management",
        matchPolicy={"mode": "two_way_po_ses"},
    )
    assert resolve_match_mode(document_type_code="DT-02", definition=definition) == "two_way_po_ses"


def test_is_clean_match_message_recognizes_modes() -> None:
    assert is_clean_match_message("2-Way Match")
    assert is_clean_match_message("Reference Match · INV-1")
    assert is_clean_match_message("Shipment Match · AWB12345678")
    assert not is_clean_match_message("Price Variance")


def test_two_way_match_clean() -> None:
    po = _po()
    inv = _invoice(subtotal=Decimal("100.00"), total=Decimal("110.00"))
    outcome = compute_two_way_po_match(po, inv)
    assert outcome.passed is True
    assert outcome.status == "2-Way Match"


def test_two_way_match_qty_over_billing() -> None:
    po = _po(po_qty=Decimal("1"))
    inv = _invoice(
        subtotal=Decimal("100.00"),
        line_items=[LineItem(description="Service", qty=Decimal("2"), amount=Decimal("100"))],
    )
    outcome = compute_two_way_po_match(po, inv)
    assert outcome.passed is False
    assert outcome.status == "Qty Variance"


def test_extract_reference_invoice_numbers_from_text() -> None:
    data = InvoiceData(
        invoice_no="CN-9",
        document_text="Credit note for invoice INV-ORIG-22",
    )
    refs = _extract_reference_invoice_numbers(data, None)
    assert "INV-ORIG-22" in refs


@pytest.mark.asyncio
async def test_reference_invoice_match_found(monkeypatch: pytest.MonkeyPatch) -> None:
    invoice = _invoice(invoice_no="CN-1", vendor="Acme")
    data = InvoiceData(
        vendor="Acme",
        document_text="Reference invoice INV-ORIG",
        total=Decimal("50"),
    )
    original = _invoice(id=5, invoice_no="INV-ORIG", vendor="Acme", total=Decimal("500"))

    async def fake_find(session, **kwargs):
        assert kwargs["reference_no"] == "INV-ORIG"
        return original

    monkeypatch.setattr(
        "app.services.document_type_match_service._find_reference_invoice",
        fake_find,
    )
    monkeypatch.setattr(
        "app.services.document_type_match_service.load_purchase_order_for_invoice",
        AsyncMock(return_value=None),
    )

    outcome = await execute_document_match(
        "reference_invoice",
        session=AsyncMock(),
        tenant_id=1,
        invoice=invoice,
        data=data,
    )
    assert outcome.passed is True
    assert "Reference Match" in outcome.message


@pytest.mark.asyncio
async def test_shipment_match_with_awb(monkeypatch: pytest.MonkeyPatch) -> None:
    invoice = _invoice(po_reference=None)
    data = InvoiceData(
        document_text="Freight invoice AWB 12345678901 for import shipment",
        total=Decimal("200"),
    )
    monkeypatch.setattr(
        "app.services.document_type_match_service.load_purchase_order_for_invoice",
        AsyncMock(return_value=None),
    )

    outcome = await execute_document_match(
        "shipment",
        session=AsyncMock(),
        tenant_id=1,
        invoice=invoice,
        data=data,
    )
    assert outcome.passed is True
    assert outcome.status == "Shipment Match"


@pytest.mark.asyncio
async def test_three_way_still_requires_grn(monkeypatch: pytest.MonkeyPatch) -> None:
    po = _po()
    inv = _invoice()
    monkeypatch.setattr(
        "app.services.document_type_match_service.load_purchase_order_for_invoice",
        AsyncMock(return_value=po),
    )

    outcome = await execute_document_match(
        "three_way_po_grn",
        session=AsyncMock(),
        tenant_id=1,
        invoice=inv,
        data=InvoiceData(po_reference="PO-100", total=Decimal("110")),
    )
    assert outcome.passed is False
    assert outcome.status == "No GRN"


@pytest.mark.asyncio
async def test_three_way_clean_with_grn(monkeypatch: pytest.MonkeyPatch) -> None:
    grn = GoodsReceipt(id=1, purchase_order_id=1, grn_qty=Decimal("1"))
    po = _po(goods_receipts=[grn])
    inv = _invoice(
        subtotal=Decimal("50.00"),
        line_items=[LineItem(description="Item", qty=Decimal("1"), amount=Decimal("50"))],
    )
    monkeypatch.setattr(
        "app.services.document_type_match_service.load_purchase_order_for_invoice",
        AsyncMock(return_value=po),
    )

    outcome = await execute_document_match(
        "three_way_po_grn",
        session=AsyncMock(),
        tenant_id=1,
        invoice=inv,
        data=InvoiceData(po_reference="PO-100", total=Decimal("55")),
    )
    assert outcome.passed is True
    assert outcome.status == "3-Way Match"
