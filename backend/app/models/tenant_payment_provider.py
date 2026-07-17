"""Tenant-connected payment provider accounts (PayPal beside Stripe Connect).

Stripe Connect continues to use stripe_accounts. This table stores PayPal
(and future) provider connections without migrating Stripe data.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PROVIDER_STRIPE = "stripe"
PROVIDER_PAYPAL = "paypal"


class TenantPaymentProviderAccount(Base):
    __tablename__ = "tenant_payment_provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_account_id",
            name="uq_tenant_payment_provider_accounts_tenant_provider_account",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_account_id: Mapped[str] = mapped_column(String(255), index=True)
    provider_merchant_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(2))
    default_currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    onboarding_status: Mapped[str | None] = mapped_column(String(64))
    payments_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    balance_visibility: Mapped[bool] = mapped_column(Boolean, default=False)
    transactions_visibility: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_id: Mapped[str | None] = mapped_column(String(128), index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_balance_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_transaction_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProviderTransaction(Base):
    """Provider-neutral transaction rows (PayPal Transaction Search, etc.)."""

    __tablename__ = "provider_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_transaction_id",
            name="uq_provider_transactions_tenant_provider_txn",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_account_id: Mapped[str] = mapped_column(String(255), index=True)
    provider_transaction_id: Mapped[str] = mapped_column(String(255), index=True)
    transaction_type: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(64), index=True)
    currency: Mapped[str | None] = mapped_column(String(3))
    gross_amount: Mapped[str | None] = mapped_column(String(32))
    fee_amount: Mapped[str | None] = mapped_column(String(32))
    net_amount: Mapped[str | None] = mapped_column(String(32))
    recipient: Mapped[str | None] = mapped_column(String(255))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaypalWebhookEvent(Base):
    __tablename__ = "paypal_webhook_events"
    __table_args__ = (
        UniqueConstraint("paypal_event_id", name="uq_paypal_webhook_events_event_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paypal_event_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    provider_account_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payload_json: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str | None] = mapped_column(String(32))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    process_error: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
