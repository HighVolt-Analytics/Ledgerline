from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict


class EntryType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


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
