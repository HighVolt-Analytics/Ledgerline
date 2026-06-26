"""Payment disbursement workflow linked to processed invoices."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, Text, func, Uuid
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaymentStatus(str, enum.Enum):
    QUEUE = "queue"
    AWAITING = "awaiting"
    SCHEDULED = "scheduled"
    PAID = "paid"
    FAILED = "failed"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
    )
    vendor_registry_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendor_registry.id", ondelete="SET NULL"),
        index=True,
    )
    vendor: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="payment_status",
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        default=PaymentStatus.QUEUE,
        index=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    paid_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invoice_approved_by: Mapped[int | None] = mapped_column()
    approvers: Mapped[list | None] = mapped_column(JSON)
    payment_intent: Mapped[str | None] = mapped_column(String(255))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), index=True)
    stripe_transfer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_payout_id: Mapped[str | None] = mapped_column(String(255))
    stripe_charge_id: Mapped[str | None] = mapped_column(String(255))
    stripe_latest_event_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
