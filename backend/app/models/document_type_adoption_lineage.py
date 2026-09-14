"""Lineage log when an org document type is adopted from the global dictionary."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DocumentTypeAdoptionLineage(Base):
    __tablename__ = "document_type_adoption_lineage"
    __table_args__ = (
        Index("ix_dt_adoption_lineage_tenant_org", "tenant_id", "org_doc_type_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    org_doc_type_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_dictionary_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_dictionary_version: Mapped[int] = mapped_column(Integer, nullable=False)
    adopted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
