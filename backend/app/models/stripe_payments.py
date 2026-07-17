"""Stripe Connect accounts, balances, transactions, and payment attempts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StripeAccount(Base):
    __tablename__ = "stripe_accounts"
    __table_args__ = (
        UniqueConstraint("stripe_account_id", name="uq_stripe_accounts_stripe_account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    stripe_account_id: Mapped[str] = mapped_column(String(255), index=True)
    account_type: Mapped[str | None] = mapped_column(String(32))
    charges_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    details_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StripeBalanceSnapshot(Base):
    __tablename__ = "stripe_balance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    stripe_account_id: Mapped[str] = mapped_column(String(255), index=True)
    available_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    pending_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class StripeTransaction(Base):
    __tablename__ = "stripe_transactions"
    __table_args__ = (
        UniqueConstraint(
            "stripe_transaction_id",
            name="uq_stripe_transactions_stripe_transaction_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    stripe_account_id: Mapped[str] = mapped_column(String(255), index=True)
    stripe_transaction_id: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    available_on: Mapped[date | None] = mapped_column(Date)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str | None] = mapped_column(String(32), index=True)
    provider_batch_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_item_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    provider_status: Mapped[str | None] = mapped_column(String(64))
    recipient_type: Mapped[str | None] = mapped_column(String(32))
    recipient_value: Mapped[str | None] = mapped_column(String(255))
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), index=True)
    stripe_transfer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_payout_id: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StripeWebhookEvent(Base):
    __tablename__ = "stripe_webhook_events"
    __table_args__ = (
        UniqueConstraint("stripe_event_id", name="uq_stripe_webhook_events_stripe_event_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stripe_event_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class VendorPaymentMethod(Base):
    __tablename__ = "vendor_payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_registry.id", ondelete="CASCADE"),
        index=True,
    )
    method_type: Mapped[str | None] = mapped_column(String(32))
    display_label: Mapped[str | None] = mapped_column(String(255))
    stripe_account_id: Mapped[str | None] = mapped_column(String(255), index=True)
    last4: Mapped[str | None] = mapped_column(String(4))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    country: Mapped[str | None] = mapped_column(String(2))
    provider: Mapped[str | None] = mapped_column(String(32), index=True)
    recipient_type: Mapped[str | None] = mapped_column(String(32))
    recipient_value: Mapped[str | None] = mapped_column(String(255))
    verification_status: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
