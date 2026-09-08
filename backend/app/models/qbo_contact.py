"""Cached QuickBooks Online vendors and customers for Pulled contacts."""

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

SOURCE_SYSTEM_QBO = "quickbooks"
ENTITY_VENDOR = "vendor"
ENTITY_CUSTOMER = "customer"
MAPPING_UNMAPPED = "unmapped"


class QboContact(Base):
    __tablename__ = "qbo_contacts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "realm_id",
            "entity_type",
            "qbo_entity_id",
            name="uq_qbo_contacts_tenant_realm_entity",
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
    realm_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(16), index=True)
    qbo_entity_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str | None] = mapped_column(String(255), index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    email_address: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    tax_number: Mapped[str | None] = mapped_column(String(64))
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mapping_status: Mapped[str] = mapped_column(
        String(32),
        default=MAPPING_UNMAPPED,
        index=True,
    )
    source_system: Mapped[str] = mapped_column(String(32), default=SOURCE_SYSTEM_QBO)
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
