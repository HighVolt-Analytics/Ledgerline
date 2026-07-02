"""Tenant scoping for invoice/PO child tables — sync + query helpers."""

from __future__ import annotations

import uuid

from sqlalchemy import event, select
from sqlalchemy.engine import Connection

from app.models.delivery_note import DeliveryNote
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.journal import JournalEntry
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder


class TenantChildMismatchError(ValueError):
    """Raised when a child row tenant_id disagrees with its parent."""


def _load_invoice_tenant(connection: Connection, invoice_id: int) -> uuid.UUID | None:
    return connection.execute(
        select(Invoice.tenant_id).where(Invoice.id == invoice_id)
    ).scalar_one_or_none()


def _load_po_tenant(connection: Connection, purchase_order_id: int) -> uuid.UUID | None:
    return connection.execute(
        select(PurchaseOrder.tenant_id).where(PurchaseOrder.id == purchase_order_id)
    ).scalar_one_or_none()


def _resolve_invoice_child_tenant(
    connection: Connection,
    *,
    tenant_id: uuid.UUID | None,
    invoice_id: int,
    label: str,
) -> uuid.UUID:
    parent_tenant = _load_invoice_tenant(connection, invoice_id)
    if parent_tenant is None:
        raise TenantChildMismatchError(f"{label}: invoice {invoice_id} not found")
    if tenant_id is None:
        return parent_tenant
    if tenant_id != parent_tenant:
        raise TenantChildMismatchError(
            f"{label}: tenant_id {tenant_id} does not match invoice tenant {parent_tenant}"
        )
    return tenant_id


def _resolve_po_child_tenant(
    connection: Connection,
    *,
    tenant_id: uuid.UUID | None,
    purchase_order_id: int,
) -> uuid.UUID:
    parent_tenant = _load_po_tenant(connection, purchase_order_id)
    if parent_tenant is None:
        raise TenantChildMismatchError(f"goods receipt: purchase order {purchase_order_id} not found")
    if tenant_id is None:
        return parent_tenant
    if tenant_id != parent_tenant:
        raise TenantChildMismatchError(
            f"goods receipt: tenant_id {tenant_id} does not match PO tenant {parent_tenant}"
        )
    return tenant_id


@event.listens_for(LineItem, "before_insert")
@event.listens_for(LineItem, "before_update")
def _sync_line_item_tenant(_mapper, connection: Connection, target: LineItem) -> None:
    target.tenant_id = _resolve_invoice_child_tenant(
        connection,
        tenant_id=target.tenant_id,
        invoice_id=target.invoice_id,
        label="line item",
    )


@event.listens_for(JournalEntry, "before_insert")
@event.listens_for(JournalEntry, "before_update")
def _sync_journal_entry_tenant(_mapper, connection: Connection, target: JournalEntry) -> None:
    target.tenant_id = _resolve_invoice_child_tenant(
        connection,
        tenant_id=target.tenant_id,
        invoice_id=target.invoice_id,
        label="journal entry",
    )


def _load_so_tenant(connection: Connection, sales_order_id: int) -> uuid.UUID | None:
    return connection.execute(
        select(SalesOrder.tenant_id).where(SalesOrder.id == sales_order_id)
    ).scalar_one_or_none()


def _resolve_so_child_tenant(
    connection: Connection,
    *,
    tenant_id: uuid.UUID | None,
    sales_order_id: int,
) -> uuid.UUID:
    parent_tenant = _load_so_tenant(connection, sales_order_id)
    if parent_tenant is None:
        raise TenantChildMismatchError(f"delivery note: sales order {sales_order_id} not found")
    if tenant_id is None:
        return parent_tenant
    if tenant_id != parent_tenant:
        raise TenantChildMismatchError(
            f"delivery note: tenant_id {tenant_id} does not match SO tenant {parent_tenant}"
        )
    return tenant_id


@event.listens_for(GoodsReceipt, "before_insert")
@event.listens_for(GoodsReceipt, "before_update")
def _sync_goods_receipt_tenant(_mapper, connection: Connection, target: GoodsReceipt) -> None:
    target.tenant_id = _resolve_po_child_tenant(
        connection,
        tenant_id=target.tenant_id,
        purchase_order_id=target.purchase_order_id,
    )


def line_items_for_invoice(tenant_id: uuid.UUID, invoice_id: int) -> tuple:
    return LineItem.tenant_id == tenant_id, LineItem.invoice_id == invoice_id


def journal_entries_for_invoice(tenant_id: uuid.UUID, invoice_id: int) -> tuple:
    return JournalEntry.tenant_id == tenant_id, JournalEntry.invoice_id == invoice_id


def goods_receipts_for_po(tenant_id: uuid.UUID, purchase_order_id: int) -> tuple:
    return GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.purchase_order_id == purchase_order_id


@event.listens_for(DeliveryNote, "before_insert")
@event.listens_for(DeliveryNote, "before_update")
def _sync_delivery_note_tenant(_mapper, connection: Connection, target: DeliveryNote) -> None:
    target.tenant_id = _resolve_so_child_tenant(
        connection,
        tenant_id=target.tenant_id,
        sales_order_id=target.sales_order_id,
    )


def delivery_notes_for_so(tenant_id: uuid.UUID, sales_order_id: int) -> tuple:
    return DeliveryNote.tenant_id == tenant_id, DeliveryNote.sales_order_id == sales_order_id
