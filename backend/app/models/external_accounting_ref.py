"""Mappings between LedgerLink entities and external accounting provider records."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExternalAccountingRef(Base):
    __tablename__ = "external_accounting_refs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "entity_type",
            "internal_entity_id",
            name="uq_external_accounting_refs_internal",
        ),
        UniqueConstraint(
            "tenant_id",
            "provider",
            "entity_type",
            "external_entity_id",
            name="uq_external_accounting_refs_external",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    internal_entity_id: Mapped[str] = mapped_column(String(255), index=True)
    external_entity_id: Mapped[str] = mapped_column(String(128), index=True)
    external_number: Mapped[str | None] = mapped_column(String(128))
    external_status: Mapped[str | None] = mapped_column(String(64))
    payload_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(512))
    sync_status: Mapped[str | None] = mapped_column(String(32), index=True)
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0)
    sync_error_code: Mapped[str | None] = mapped_column(String(64))
    sync_error_message: Mapped[str | None] = mapped_column(String(512))
    sync_direction: Mapped[str | None] = mapped_column(String(16), index=True)
    source_system: Mapped[str | None] = mapped_column(String(32))
    last_remote_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_status: Mapped[str | None] = mapped_column(String(32), index=True)
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    amount_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_fully_paid: Mapped[bool | None] = mapped_column(Boolean)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
