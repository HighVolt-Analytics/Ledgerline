"""Bank feed / cash reconciliation domain (separate from daily RC and Xero sync)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

JsonType = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class BankConnectionType(str, enum.Enum):
    MANUAL = "manual"
    AGGREGATOR = "aggregator"


class BankAccountStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class BankFeedSource(str, enum.Enum):
    CSV = "csv"
    OFX = "ofx"
    PDF = "pdf"
    PLAID = "plaid"


class BankFeedImportStatus(str, enum.Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class BankTxnDirection(str, enum.Enum):
    """GL-oriented bank movement: debit = money out, credit = money in."""

    DEBIT = "debit"
    CREDIT = "credit"


class BankTxnMatchStatus(str, enum.Enum):
    UNMATCHED = "unmatched"
    SUGGESTED = "suggested"
    MATCHED = "matched"
    EXCLUDED = "excluded"
    POSTED = "posted"


class BankMatchEntityType(str, enum.Enum):
    PAYMENT = "payment"
    COLLECTION = "collection"
    INVOICE = "invoice"
    CLAIM = "claim"


class BankMatchMethod(str, enum.Enum):
    AUTO = "auto"
    SUGGESTED = "suggested"
    MANUAL = "manual"


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        Index("ix_bank_accounts_tenant_id", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    account_number: Mapped[str | None] = mapped_column(String(64))
    account_mask: Mapped[str | None] = mapped_column(String(32))
    coa_account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    coa_account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    connection_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=BankConnectionType.MANUAL.value
    )
    external_item_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=BankAccountStatus.ACTIVE.value, index=True
    )
    # Optional StatementParseProfile id (e.g. generic_v1, eu_decimal_v1). None → generic_v1.
    statement_parse_profile_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PendingBankAccount(Base):
    """Bank statement uploaded without a registered account — awaiting registration."""

    __tablename__ = "pending_bank_accounts"
    __table_args__ = (
        Index("ix_pending_bank_accounts_tenant_id", "tenant_id"),
        Index(
            "ix_pending_bank_accounts_file_sha256",
            "tenant_id",
            "file_sha256",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    detected_name: Mapped[str | None] = mapped_column(String(255))
    detected_account_number: Mapped[str | None] = mapped_column(String(64))
    detected_currency: Mapped[str | None] = mapped_column(String(3))
    filename: Mapped[str | None] = mapped_column(String(512))
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    extracted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    parse_meta: Mapped[dict[str, Any] | list | None] = mapped_column(JsonType)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    promoted_bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BankFeedImport(Base):
    __tablename__ = "bank_feed_imports"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "file_sha256",
            name="uq_bank_feed_imports_file_sha256",
        ),
        Index("ix_bank_feed_imports_tenant_id", "tenant_id"),
        Index("ix_bank_feed_imports_bank_account_id", "bank_account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default=BankFeedSource.CSV.value)
    filename: Mapped[str | None] = mapped_column(String(512))
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_report: Mapped[dict[str, Any] | list | None] = mapped_column(JsonType)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "fingerprint",
            name="uq_bank_transactions_fingerprint",
        ),
        Index(
            "uq_bank_transactions_external_id",
            "tenant_id",
            "bank_account_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
            sqlite_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_bank_transactions_tenant_id", "tenant_id"),
        Index("ix_bank_transactions_bank_account_id", "bank_account_id"),
        Index("ix_bank_transactions_match_status", "tenant_id", "match_status"),
        Index("ix_bank_transactions_txn_date", "tenant_id", "txn_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False
    )
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_feed_imports.id", ondelete="SET NULL")
    )
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_normalized: Mapped[str] = mapped_column(Text, nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    external_id: Mapped[str | None] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    match_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=BankTxnMatchStatus.UNMATCHED.value,
    )
    posted_journal_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_batches.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    category_coa: Mapped[str | None] = mapped_column(String(255))
    review_flags: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BankTransactionMatch(Base):
    __tablename__ = "bank_transaction_matches"
    __table_args__ = (
        Index("ix_bank_transaction_matches_tenant_id", "tenant_id"),
        Index("ix_bank_transaction_matches_txn_id", "bank_transaction_id"),
        Index(
            "ix_bank_transaction_matches_entity",
            "tenant_id",
            "matched_type",
            "matched_id",
        ),
        Index(
            "ix_bank_transaction_matches_active",
            "bank_transaction_id",
            postgresql_where=text("unmatched_at IS NULL"),
            sqlite_where=text("unmatched_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    bank_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False
    )
    matched_type: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_id: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    match_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    match_reasons: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    matched_by: Mapped[str | None] = mapped_column(String(255))
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    unmatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unmatch_reason: Mapped[str | None] = mapped_column(Text)


class BankTransactionNote(Base):
    __tablename__ = "bank_transaction_notes"
    __table_args__ = (
        Index("ix_bank_transaction_notes_tenant_txn", "tenant_id", "bank_transaction_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    bank_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
