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

    invoice: Mapped["Invoice"] = relationship(back_populates="journal_entries")
