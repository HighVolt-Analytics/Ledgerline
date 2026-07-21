"""Durable outbound accounting export ledger (provider-neutral, Xero Phase 1)."""

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

PROVIDER_XERO = "xero"
DIRECTION_OUTBOUND = "outbound"
TXN_SUPPLIER_INVOICE = "SUPPLIER_INVOICE"

STATUS_READY = "READY"
STATUS_IN_FLIGHT = "IN_FLIGHT"
STATUS_SUCCESS = "SUCCESS"
STATUS_RETRY_PENDING = "RETRY_PENDING"
STATUS_HUMAN_REVIEW = "HUMAN_REVIEW"
STATUS_FAILED_TERMINAL = "FAILED_TERMINAL"

ATTACHMENT_PENDING = "pending"
ATTACHMENT_SUCCESS = "success"
ATTACHMENT_FAILED = "failed"
ATTACHMENT_MISSING = "missing"
ATTACHMENT_SKIPPED = "skipped"


class AccountingExportLedger(Base):
    __tablename__ = "accounting_export_ledger"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "qll_transaction_id",
            "payload_version",
            name="uq_accounting_export_ledger_txn_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "provider",
            "idempotency_key",
            name="uq_accounting_export_ledger_idempotency",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, default=PROVIDER_XERO)
    qll_transaction_id: Mapped[str] = mapped_column(String(64), index=True)
    source_invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
    )
    source_document_id: Mapped[str | None] = mapped_column(String(64))
    transaction_type: Mapped[str] = mapped_column(String(32), default=TXN_SUPPLIER_INVOICE)
    direction: Mapped[str] = mapped_column(String(16), default=DIRECTION_OUTBOUND)
    status: Mapped[str] = mapped_column(String(32), index=True, default=STATUS_READY)
    payload_version: Mapped[int] = mapped_column(Integer, default=1)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    canonical_json: Mapped[str | None] = mapped_column(Text)
    request_payload_json: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    external_number: Mapped[str | None] = mapped_column(String(128))
    external_status: Mapped[str | None] = mapped_column(String(64))
    external_contact_id: Mapped[str | None] = mapped_column(String(128))
    external_currency: Mapped[str | None] = mapped_column(String(8))
    external_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    xero_tenant_id: Mapped[str | None] = mapped_column(String(128))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_bucket: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    request_correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    last_response_summary: Mapped[str | None] = mapped_column(Text)
    attachment_status: Mapped[str | None] = mapped_column(String(32))
    attachment_external_id: Mapped[str | None] = mapped_column(String(128))
    attachment_error: Mapped[str | None] = mapped_column(String(512))
    divergence_flags_json: Mapped[str | None] = mapped_column(Text)
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    amount_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_fully_paid: Mapped[bool | None] = mapped_column(Boolean)
    last_remote_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
