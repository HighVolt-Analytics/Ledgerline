"""Goods receipt (GRN) linked to a purchase order."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.purchase_order import PurchaseOrder


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        index=True,
    )
    grn_qty: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    grn_date: Mapped[date | None] = mapped_column(Date)
    receiver: Mapped[str | None] = mapped_column(String(255))
    condition_note: Mapped[str | None] = mapped_column(String(255))
    grn_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="goods_receipts")
