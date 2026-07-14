"""Delivery note linked to a sales order."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.delivery_note_line import DeliveryNoteLine
    from app.models.sales_order import SalesOrder


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"),
        index=True,
    )
    dn_qty: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    dn_uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dn_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    dn_date: Mapped[date | None] = mapped_column(Date)
    shipper: Mapped[str | None] = mapped_column(String(255))
    condition_note: Mapped[str | None] = mapped_column(String(255))
    dn_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    sales_order: Mapped["SalesOrder"] = relationship(back_populates="delivery_notes")
    lines: Mapped[list["DeliveryNoteLine"]] = relationship(
        back_populates="delivery_note",
        cascade="all, delete-orphan",
    )
