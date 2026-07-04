
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Purchase Management rule book §4.3 and coding inheritance."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.schemas.rule_book_config import (
    PostToAccounts,
    PurchaseMatchOn,
    PurchaseRule,
    validate_rule_book_config_payload,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.purchase.purchase_coding_service import code_po_from_invoice, inherit_po_coding_to_invoice
from app.services.purchase.purchase_match_service import sync_purchase_order_from_invoice
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.services.rule_book.rule_book_mapper import resolve_config_mapping
from app.services.rule_book.rule_engine import EvalDocument, match_purchase_rule


def _rule(**kwargs) -> PurchaseRule:
    defaults = {
        "id": "pr-test",
        "name": "Test PO rule",
        "enabled": True,
        "priority": 100,
        "match_on": PurchaseMatchOn(
            po_prefix="PO-TEST-",
            grn_linked_to_po=True,
            invoice_references_po=True,
        ),
        "post_to": PostToAccounts(
            ledger="Cloud Hosting Expense",
            sub_ledger="AWS Production",
            tax_account="GST Paid",
            payable_account="Accounts Payable",
        ),
    }
    defaults.update(kwargs)
    return PurchaseRule(**defaults)


def test_purchase_rule_requires_po_prefix_match() -> None:
    rules = [_rule()]
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-1",
        vendor="Acme Corp",
        po="PO-TEST-99",
        document_type="invoice",
    )
    assert match_purchase_rule(doc, rules) is not None

    vendor_only = EvalDocument(
        id="2",
        doc_number="DOC-2",
        invoice_no="INV-2",
        vendor="Acme Beverage Corp",
        document_type="invoice",
    )
    vendor_rule = _rule(
        match_on=PurchaseMatchOn(vendor_contains="Beverage", invoice_references_po=True)
    )
    assert match_purchase_rule(vendor_only, [vendor_rule]) is None


def test_purchase_rule_invoice_requires_invoice_references_po_flag() -> None:
    rules = [
        _rule(
            match_on=PurchaseMatchOn(
                po_prefix="PO-TEST-",
                invoice_references_po=False,
            )
        )
    ]
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-1",
        vendor="Acme",
        po="PO-TEST-1",
        document_type="invoice",
    )
    assert match_purchase_rule(doc, rules) is None


def test_purchase_rule_grn_requires_grn_linked_flag() -> None:
    rules = [
        _rule(
            match_on=PurchaseMatchOn(
                po_prefix="PO-TEST-",
                grn_linked_to_po=False,
            )
        )
    ]
    doc = EvalDocument(
        id="1",
        doc_number="GRN-1",
        invoice_no="",
        vendor="Acme",
        po="PO-TEST-1",
        document_type="grn",
    )
    assert match_purchase_rule(doc, rules) is None

    rules[0].match_on.grn_linked_to_po = True
    assert match_purchase_rule(doc, rules) is not None


def test_purchase_rule_vendor_narrowing_is_anded_with_po() -> None:
    rules = [
        _rule(
            match_on=PurchaseMatchOn(
                po_prefix="PO-BEV-",
                vendor_contains="Beverage",
                invoice_references_po=True,
                grn_linked_to_po=True,
            )
        )
    ]
    doc = EvalDocument(
        id="1",
        doc_number="DOC-1",
        invoice_no="INV-1",
        vendor="Sysco Australia",
        po="PO-BEV-99",
        document_type="invoice",
    )
    assert match_purchase_rule(doc, rules) is None

    doc_ok = EvalDocument(
        id="2",
        doc_number="DOC-2",
        invoice_no="INV-2",
        vendor="Sysco Beverage Australia",
        po="PO-BEV-99",
        document_type="invoice",
    )
    assert match_purchase_rule(doc_ok, rules) is not None


@pytest.mark.asyncio
async def test_sync_purchase_order_codes_po_and_inherits_to_invoice(
    db_session: AsyncSession,
) -> None:
    config = validate_rule_book_config_payload(
        await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    )
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        po_reference="PO-CLOUD-2026-999",
        invoice_no="PO-CLOUD-2026-999",
        route_target=ROUTE_PURCHASE,
        document_type_code="DT-01",
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("100.00"),
        total=Decimal("110.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="EC2",
            qty=Decimal("1"),
            unit_price=Decimal("100.00"),
            amount=Decimal("100.00"),
        )
    )
    await db_session.flush()

    po_loaded = (
        await db_session.execute(
            select(Invoice)
            .where(Invoice.id == po_doc.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    po = await sync_purchase_order_from_invoice(db_session, po_loaded)
    assert po is not None
    assert po.ledger == "Cloud Hosting Expense"
    assert po.sub_ledger == "AWS Production"
    assert po.purchase_rule_id == "DT-01"

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        po_reference="PO-CLOUD-2026-999",
        invoice_no="AWS-TEST-1",
        route_target=ROUTE_PURCHASE,
        document_type_code="DT-01",
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("100.00"),
        total=Decimal("110.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="EC2",
            qty=Decimal("1"),
            unit_price=Decimal("100.00"),
            amount=Decimal("100.00"),
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
    await sync_purchase_order_from_invoice(db_session, loaded)
    assert loaded.account_name == "Cloud Hosting Expense"

    hit = resolve_config_mapping(loaded, config, purchase_order=po)
    assert hit.rule_type == "Document type"
    assert hit.mapping.account_name == "Cloud Hosting Expense"


@pytest.mark.asyncio
async def test_code_po_from_invoice_persists_ledger(db_session: AsyncSession) -> None:
    config = validate_rule_book_config_payload(
        await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    )
    po = PurchaseOrder(tenant_id=TESTING_TENANT_UUID, po_number="PO-CLOUD-2026-100")
    db_session.add(po)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        po_reference="PO-CLOUD-2026-100",
        invoice_no="AWS-2",
        route_target=ROUTE_PURCHASE,
        document_type_code="DT-01",
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()

    coded = code_po_from_invoice(po, inv, config)
    assert coded is True
    assert po.ledger == "Cloud Hosting Expense"
    assert inherit_po_coding_to_invoice(po, inv) is True
    assert inv.account_name == "Cloud Hosting Expense"
