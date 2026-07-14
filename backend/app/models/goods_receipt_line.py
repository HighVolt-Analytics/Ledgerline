"""Line on a goods receipt for line-level three-way match."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.goods_receipt import GoodsReceipt
    from app.models.purchase_order_line import PurchaseOrderLine


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    goods_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"),
        index=True,
    )
    purchase_order_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    uom: Mapped[str | None] = mapped_column(String(32), nullable=True)

    goods_receipt: Mapped["GoodsReceipt"] = relationship(back_populates="lines")
    purchase_order_line: Mapped["PurchaseOrderLine | None"] = relationship(
        back_populates="receipt_lines",
    )
