"""Line item ORM model."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.invoice import Invoice


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sub_ledger: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gl_mapping_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gl_mapping_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    gl_mapping_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")
