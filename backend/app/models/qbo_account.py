"""Cached QuickBooks Online chart of accounts (including subaccounts)."""

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


class QboAccount(Base):
    __tablename__ = "qbo_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "realm_id",
            "qbo_account_id",
            name="uq_qbo_accounts_tenant_realm_account",
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
    qbo_account_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str | None] = mapped_column(String(255), index=True)
    acct_num: Mapped[str | None] = mapped_column(String(64), index=True)
    fully_qualified_name: Mapped[str | None] = mapped_column(String(512))
    account_type: Mapped[str | None] = mapped_column(String(64))
    account_sub_type: Mapped[str | None] = mapped_column(String(64))
    classification: Mapped[str | None] = mapped_column(String(64))
    parent_ref: Mapped[str | None] = mapped_column(String(128), index=True)
    sub_account: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    currency_code: Mapped[str | None] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(String(512))
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
