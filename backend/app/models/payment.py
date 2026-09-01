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
    currency: Mapped[str] = mapped_column(String(3), default="")
    payment_fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    bank_payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fx_variance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
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
    # Set once this payment has been included in a generated batch bank
    # payment file (e.g. an AU ABA export) -- lets the UI show "already
    # exported" and stops the same Scheduled payment from silently being
    # bundled into two different batch files.
    bank_file_batch_reference: Mapped[str | None] = mapped_column(String(64), index=True)
    bank_file_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
