"""Persisted Xero tax-rate rows (tenant-scoped)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

SOURCE_SYSTEM_XERO = "xero"


class XeroTaxRate(Base):
    __tablename__ = "xero_tax_rates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "xero_tenant_id",
            "tax_type",
            name="uq_xero_tax_rates_tenant_tax_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    accounting_integration_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_integrations.id", ondelete="CASCADE"),
        index=True,
    )
    xero_tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    tax_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    effective_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    display_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    can_apply_to_assets: Mapped[bool | None] = mapped_column(Boolean)
    can_apply_to_equity: Mapped[bool | None] = mapped_column(Boolean)
    can_apply_to_expenses: Mapped[bool | None] = mapped_column(Boolean)
    can_apply_to_liabilities: Mapped[bool | None] = mapped_column(Boolean)
    can_apply_to_revenue: Mapped[bool | None] = mapped_column(Boolean)
    source_system: Mapped[str] = mapped_column(String(32), default=SOURCE_SYSTEM_XERO)
    sync_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
