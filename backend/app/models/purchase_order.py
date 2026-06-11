"""Purchase order and goods receipt for three-way matching."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.goods_receipt import GoodsReceipt


class PurchaseOrderStatus(str, enum.Enum):
    OPEN = "open"
    MATCHED = "matched"
    VARIANCE_PENDING = "variance_pending"
    CLOSED = "closed"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), index=True)
    po_number: Mapped[str] = mapped_column(String(100), index=True)
    vendor: Mapped[str | None] = mapped_column(String(255))
    po_date: Mapped[date | None] = mapped_column(Date)
    item: Mapped[str | None] = mapped_column(String(255))
    requestor: Mapped[str | None] = mapped_column(String(255))
    po_qty: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("1"))
    po_unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )
    po_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )
    variance_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    ledger: Mapped[str | None] = mapped_column(String(255))
    sub_ledger: Mapped[str | None] = mapped_column(String(255))
    tax_account: Mapped[str | None] = mapped_column(String(100))
    payable_account: Mapped[str | None] = mapped_column(String(100))
    purchase_rule_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        Enum(
            PurchaseOrderStatus,
            name="purchase_order_status",
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        default=PurchaseOrderStatus.OPEN,
    )
    three_way_match_status: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    goods_receipts: Mapped[list[GoodsReceipt]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )
