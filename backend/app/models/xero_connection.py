"""Xero organisation connections linked to an accounting integration."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class XeroConnection(Base):
    __tablename__ = "xero_connections"
    __table_args__ = (
        UniqueConstraint(
            "accounting_integration_id",
            "xero_connection_id",
            name="uq_xero_connections_integration_connection",
        ),
        UniqueConstraint(
            "tenant_id",
            "xero_tenant_id",
            name="uq_xero_connections_tenant_xero_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    accounting_integration_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_integrations.id", ondelete="CASCADE"),
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    xero_connection_id: Mapped[str] = mapped_column(String(128), index=True)
    xero_tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    xero_tenant_type: Mapped[str | None] = mapped_column(String(64))
    xero_tenant_name: Mapped[str | None] = mapped_column(String(255))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
