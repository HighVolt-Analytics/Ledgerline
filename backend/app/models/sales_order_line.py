"""Line on a sales order for line-level three-way match."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.delivery_note_line import DeliveryNoteLine
    from app.models.sales_order import SalesOrder


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"

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
    line_no: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    line_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    sales_order: Mapped["SalesOrder"] = relationship(back_populates="lines")
    delivery_lines: Mapped[list["DeliveryNoteLine"]] = relationship(
        back_populates="sales_order_line",
    )
