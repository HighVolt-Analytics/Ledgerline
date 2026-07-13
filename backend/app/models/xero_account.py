"""Persisted Xero chart-of-accounts rows (tenant-scoped)."""

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

SOURCE_SYSTEM_XERO = "xero"


class XeroAccount(Base):
    __tablename__ = "xero_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "xero_tenant_id",
            "xero_account_id",
            name="uq_xero_accounts_tenant_account",
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
    xero_account_id: Mapped[str] = mapped_column(String(128), index=True)
    code: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    account_type: Mapped[str | None] = mapped_column(String(64))
    account_class: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    tax_type: Mapped[str | None] = mapped_column(String(64))
    currency_code: Mapped[str | None] = mapped_column(String(8))
    enable_payments_to_account: Mapped[bool | None] = mapped_column(Boolean)
    show_in_expense_claims: Mapped[bool | None] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(String(512))
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
