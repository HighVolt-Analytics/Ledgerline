"""Per-page content fingerprints for ingest duplicate detection."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InvoicePageFingerprint(Base):
    __tablename__ = "invoice_page_fingerprints"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "page_index",
            name="uq_invoice_page_fingerprints_invoice_page",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id"),
        index=True,
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
