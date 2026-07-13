"""Persisted Xero contacts with optional LedgerLink mapping status."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SOURCE_SYSTEM_XERO = "xero"
MAPPING_UNMAPPED = "unmapped"
MAPPING_MAPPED = "mapped"
MAPPING_CONFLICT = "mapping_conflict"
MAPPING_IGNORED = "ignored"


class XeroContact(Base):
    __tablename__ = "xero_contacts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "xero_tenant_id",
            "xero_contact_id",
            name="uq_xero_contacts_tenant_contact",
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
    xero_contact_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str | None] = mapped_column(String(255), index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    email_address: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    contact_status: Mapped[str | None] = mapped_column(String(32), index=True)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_number: Mapped[str | None] = mapped_column(String(64))
    default_currency: Mapped[str | None] = mapped_column(String(8))
    accounts_payable_tax_type: Mapped[str | None] = mapped_column(String(64))
    accounts_receivable_tax_type: Mapped[str | None] = mapped_column(String(64))
    mapping_status: Mapped[str] = mapped_column(
        String(32),
        default=MAPPING_UNMAPPED,
        index=True,
    )
    mapped_vendor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mapped_customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_system: Mapped[str] = mapped_column(String(32), default=SOURCE_SYSTEM_XERO)
    sync_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    last_remote_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
