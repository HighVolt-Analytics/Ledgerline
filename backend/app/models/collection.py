"""Collections workflow for accounts receivable."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, Text, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollectionStatus(str, enum.Enum):
    QUEUE = "queue"
    AWAITING = "awaiting"
    RECEIVED = "received"
    FAILED = "failed"


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
    )
    customer_registry_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_registry.id", ondelete="SET NULL"),
        index=True,
    )
    customer: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    status: Mapped[CollectionStatus] = mapped_column(
        Enum(
            CollectionStatus,
            name="collection_status",
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        default=CollectionStatus.QUEUE,
        index=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    received_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
