"""Line on a delivery note for line-level three-way match."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.delivery_note import DeliveryNote
    from app.models.sales_order_line import SalesOrderLine


class DeliveryNoteLine(Base):
    __tablename__ = "delivery_note_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    delivery_note_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_notes.id", ondelete="CASCADE"),
        index=True,
    )
    sales_order_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    uom: Mapped[str | None] = mapped_column(String(32), nullable=True)

    delivery_note: Mapped["DeliveryNote"] = relationship(back_populates="lines")
    sales_order_line: Mapped["SalesOrderLine | None"] = relationship(
        back_populates="delivery_lines",
    )
