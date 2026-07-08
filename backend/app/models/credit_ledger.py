"""Immutable credit usage and Azure cost ledger per tenant."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_credit_ledger_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits_per_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_at_event: Mapped[str | None] = mapped_column(String(20), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    azure_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    azure_cost_breakdown_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
