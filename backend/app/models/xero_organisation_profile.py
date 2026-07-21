"""Persisted Xero organisation profile snapshot."""

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


class XeroOrganisationProfile(Base):
    __tablename__ = "xero_organisation_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "xero_tenant_id",
            name="uq_xero_organisation_profiles_tenant_org",
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
    organisation_id: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(String(255))
    legal_name: Mapped[str | None] = mapped_column(String(255))
    base_currency: Mapped[str | None] = mapped_column(String(8))
    country_code: Mapped[str | None] = mapped_column(String(8))
    organisation_status: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
