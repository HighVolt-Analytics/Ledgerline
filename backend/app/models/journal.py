"""Journal entry ORM model."""

import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.invoice import Invoice


class EntryType(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalEntryKind(str, enum.Enum):
    INVOICE_ACCRUAL = "invoice_accrual"
    PAYMENT_SETTLEMENT = "payment_settlement"
    COLLECTION_SETTLEMENT = "collection_settlement"


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
    )
    date: Mapped[date] = mapped_column(Date)
    account_code: Mapped[str] = mapped_column(String(20))
    account_name: Mapped[str] = mapped_column(String(255))
    debit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    entry_type: Mapped[EntryType] = mapped_column(
        Enum(
            EntryType,
            name="entry_type",
            values_callable=lambda types: [t.value for t in types],
        )
    )
    vendor_registry_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendor_registry.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_registry_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_registry.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entry_kind: Mapped[JournalEntryKind] = mapped_column(
        Enum(
            JournalEntryKind,
            name="journal_entry_kind",
            values_callable=lambda kinds: [k.value for k in kinds],
        ),
        default=JournalEntryKind.INVOICE_ACCRUAL,
        index=True,
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    invoice: Mapped["Invoice"] = relationship(back_populates="journal_entries")
