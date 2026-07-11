from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict


class EntryType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalEntryKind(str, Enum):
    INVOICE_ACCRUAL = "invoice_accrual"
    PAYMENT_SETTLEMENT = "payment_settlement"
    COLLECTION_SETTLEMENT = "collection_settlement"


class JournalEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    date: date
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    entry_type: EntryType
    vendor_registry_id: int | None = None
    customer_registry_id: int | None = None
    entry_kind: JournalEntryKind = JournalEntryKind.INVOICE_ACCRUAL
    payment_id: int | None = None
    collection_id: int | None = None
