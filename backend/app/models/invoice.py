"""Invoice ORM model."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

_JsonColumn = JSON().with_variant(JSONB, "postgresql")

if TYPE_CHECKING:
    from app.models.journal import JournalEntry
    from app.models.line_item import LineItem


class PurchaseDocumentType(str, enum.Enum):
    PO = "po"
    GRN = "grn"
    INVOICE = "invoice"


class SalesDocumentType(str, enum.Enum):
    SO = "so"
    DN = "dn"
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
    __table_args__ = (UniqueConstraint("tenant_id", "file_hash", name="uq_invoice_tenant_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    connected_mailbox_id: Mapped[int | None] = mapped_column(
        ForeignKey("connected_mailboxes.id"),
        nullable=True,
    )
    whatsapp_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connected_whatsapp_accounts.id"),
        nullable=True,
    )
    viber_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connected_viber_accounts.id"),
        nullable=True,
    )
    vendor: Mapped[str | None] = mapped_column(String(255))
    abn: Mapped[str | None] = mapped_column(String(11))
    billing_address: Mapped[str | None] = mapped_column(Text)
    bank_bsb: Mapped[str | None] = mapped_column(String(16))
    bank_account: Mapped[str | None] = mapped_column(String(32))
    document_ref: Mapped[str | None] = mapped_column(String(32), index=True)
    invoice_no: Mapped[str | None] = mapped_column(String(100), index=True)
    po_reference: Mapped[str | None] = mapped_column(String(100))
    so_reference: Mapped[str | None] = mapped_column(String(100), index=True)
    cost_centre: Mapped[str | None] = mapped_column(String(100))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="")
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gst: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
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
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    business_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    normalized_filename: Mapped[str | None] = mapped_column(String(255), index=True)
    duplicate_review_suggested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    raw_file_path: Mapped[str | None] = mapped_column(Text)
    email_sender: Mapped[str | None] = mapped_column(String(255))
    email_subject: Mapped[str | None] = mapped_column(String(500))
    email_attachment_name: Mapped[str | None] = mapped_column(String(255))
    email_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    capture_source: Mapped[str | None] = mapped_column(String(32))
    uploaded_by_name: Mapped[str | None] = mapped_column(String(255))
    uploaded_by_email: Mapped[str | None] = mapped_column(String(255))
    storage_vendor_slug: Mapped[str | None] = mapped_column(String(100))
    validation_results: Mapped[str | None] = mapped_column(Text)
    account_code: Mapped[str | None] = mapped_column(String(20))
    account_name: Mapped[str | None] = mapped_column(String(255))
    route_target: Mapped[str | None] = mapped_column(String(100), index=True)
    team_expense_kind: Mapped[str | None] = mapped_column(String(32))
    linked_advance_invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched_rule_ids: Mapped[str | None] = mapped_column(Text)
    vendor_confidence: Mapped[float | None] = mapped_column(Float)
    evaluation_status: Mapped[str | None] = mapped_column(String(32), index=True)
    purchase_document_type: Mapped[str | None] = mapped_column(String(16), index=True)
    sales_document_type: Mapped[str | None] = mapped_column(String(16), index=True)
    document_type_code: Mapped[str | None] = mapped_column(String(16), index=True)
    document_type_confidence: Mapped[float | None] = mapped_column(Float)
    llm_suggested_dt: Mapped[str | None] = mapped_column(String(16), nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    document_text: Mapped[str | None] = mapped_column(Text)
    document_heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extracted_fields: Mapped[dict[str, Any] | None] = mapped_column(_JsonColumn, nullable=True)
    processing_overrides: Mapped[dict[str, Any] | None] = mapped_column(_JsonColumn, nullable=True)
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
