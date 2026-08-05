"""Sales order and delivery notes for three-way matching."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, func, Uuid, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

_JsonColumn = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.delivery_note import DeliveryNote
    from app.models.sales_order_line import SalesOrderLine


class SalesOrderStatus(str, enum.Enum):
    OPEN = "open"
    MATCHED = "matched"
    VARIANCE_PENDING = "variance_pending"
    CLOSED = "closed"


class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    so_number: Mapped[str] = mapped_column(String(100), index=True)
    customer: Mapped[str | None] = mapped_column(String(255))
    so_date: Mapped[date | None] = mapped_column(Date)
    item: Mapped[str | None] = mapped_column(String(255))
    requestor: Mapped[str | None] = mapped_column(String(255))
    so_qty: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("1"))
    so_unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    so_uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    so_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )
    so_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )
    variance_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    variance_approval_chain: Mapped[dict[str, Any] | None] = mapped_column(_JsonColumn, nullable=True)
    ledger: Mapped[str | None] = mapped_column(String(255))
    sub_ledger: Mapped[str | None] = mapped_column(String(255))
    tax_account: Mapped[str | None] = mapped_column(String(100))
    receivable_account: Mapped[str | None] = mapped_column(String(100))
    sales_rule_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[SalesOrderStatus] = mapped_column(
        Enum(
            SalesOrderStatus,
            name="sales_order_status",
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        default=SalesOrderStatus.OPEN,
    )
    three_way_match_status: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    delivery_notes: Mapped[list["DeliveryNote"]] = relationship(
        back_populates="sales_order",
        cascade="all, delete-orphan",
    )
    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="sales_order",
        cascade="all, delete-orphan",
        order_by="SalesOrderLine.line_no",
    )
