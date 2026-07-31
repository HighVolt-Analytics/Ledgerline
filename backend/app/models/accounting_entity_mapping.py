"""Tenant-scoped durable mappings between LedgerLink keys and Xero entities."""

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

MAPPING_GL_ACCOUNT = "gl_account"
MAPPING_TAX = "tax_code"
MAPPING_TRACKING = "tracking"
MAPPING_SUPPLIER = "supplier"

PROVIDER_XERO = "xero"


class AccountingEntityMapping(Base):
    __tablename__ = "accounting_entity_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "xero_tenant_id",
            "mapping_type",
            "source_key",
            name="uq_accounting_entity_mappings_org_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, default=PROVIDER_XERO)
    xero_tenant_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    mapping_type: Mapped[str] = mapped_column(String(32), index=True)
    source_key: Mapped[str] = mapped_column(String(255))
    source_label: Mapped[str | None] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(128))
    external_code: Mapped[str | None] = mapped_column(String(128))
    external_name: Mapped[str | None] = mapped_column(String(255))
    external_option_id: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
