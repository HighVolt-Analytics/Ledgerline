"""OAuth-connected accounting providers (Xero, QuickBooks Online)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AccountingProvider(str, enum.Enum):
    XERO = "xero"
    QUICKBOOKS_ONLINE = "quickbooks_online"


class AccountingIntegrationStatus(str, enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"
    ERROR = "error"
    NEEDS_REAUTH = "needs_reauth"
    ORGANISATION_SELECTION_REQUIRED = "organisation_selection_required"


class AccountingIntegration(Base):
    __tablename__ = "accounting_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_accounting_integrations_tenant_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default=AccountingIntegrationStatus.DISCONNECTED.value)
    provider_tenant_id: Mapped[str | None] = mapped_column(String(128), index=True)
    xero_connection_id: Mapped[str | None] = mapped_column(String(128), index=True)
    provider_tenant_type: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(255))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str | None] = mapped_column(String(512))
    connected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(String(512))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def is_connected(self) -> bool:
        return (
            self.status == AccountingIntegrationStatus.CONNECTED.value
            and bool(self.access_token_encrypted)
        )
