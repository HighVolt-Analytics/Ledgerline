"""Invoice ORM model."""

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.journal import JournalEntry
    from app.models.line_item import LineItem


class PurchaseDocumentType(str, enum.Enum):
    PO = "po"
    GRN = "grn"
    INVOICE = "invoice"


class InvoiceStatus(str, enum.Enum):
    PENDING = "pending"
    PARSING = "parsing"
    VALIDATING = "validating"
    MAPPING = "mapping"
    JOURNALING = "journaling"
    RECONCILING = "reconciling"
    PROCESSED = "processed"
    EXCEPTION = "exception"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    REJECTED = "rejected"


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("org_id", "file_hash", name="uq_invoice_org_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), index=True)
    connected_mailbox_id: Mapped[int | None] = mapped_column(
        ForeignKey("connected_mailboxes.id"),
        nullable=True,
    )
    whatsapp_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connected_whatsapp_accounts.id"),
        nullable=True,
    )
    vendor: Mapped[str | None] = mapped_column(String(255))
    abn: Mapped[str | None] = mapped_column(String(11))
    billing_address: Mapped[str | None] = mapped_column(Text)
    bank_bsb: Mapped[str | None] = mapped_column(String(16))
    bank_account: Mapped[str | None] = mapped_column(String(32))
    invoice_no: Mapped[str | None] = mapped_column(String(100), index=True)
    po_reference: Mapped[str | None] = mapped_column(String(100))
    cost_centre: Mapped[str | None] = mapped_column(String(100))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gst: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(
            InvoiceStatus,
            name="invoice_status",
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        default=InvoiceStatus.PENDING,
        index=True,
    )
    file_hash: Mapped[str | None] = mapped_column(String(64))
    raw_file_path: Mapped[str | None] = mapped_column(Text)
    email_sender: Mapped[str | None] = mapped_column(String(255))
    email_subject: Mapped[str | None] = mapped_column(String(500))
    email_attachment_name: Mapped[str | None] = mapped_column(String(255))
    email_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    capture_source: Mapped[str | None] = mapped_column(String(32))
    storage_vendor_slug: Mapped[str | None] = mapped_column(String(100))
    validation_results: Mapped[str | None] = mapped_column(Text)
    account_code: Mapped[str | None] = mapped_column(String(20))
    account_name: Mapped[str | None] = mapped_column(String(255))
    route_target: Mapped[str | None] = mapped_column(String(100), index=True)
    matched_rule_ids: Mapped[str | None] = mapped_column(Text)
    vendor_confidence: Mapped[float | None] = mapped_column(Float)
    evaluation_status: Mapped[str | None] = mapped_column(String(32), index=True)
    purchase_document_type: Mapped[str | None] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    journal_entries: Mapped[list["JournalEntry"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
