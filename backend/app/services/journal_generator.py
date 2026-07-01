from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice
from app.models.journal import EntryType
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.account_mapper import AccountMapping


@dataclass
class JournalLine:
    date: date
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    entry_type: EntryType


def generate_entries(
    invoice: Invoice,
    mapping: AccountMapping,
    *,
    config: RuleBookConfigPayload | None = None,
) -> list[JournalLine]:
    from app.schemas.rule_book_config import RuleBookConfigPayload as ConfigPayload
    from app.services.fx_posting_service import generate_booking_entries

    cfg = config or ConfigPayload()
    return generate_booking_entries(invoice, mapping, config=cfg)


def is_balanced(lines: list[JournalLine]) -> bool:
    dr = sum(line.debit for line in lines)
    cr = sum(line.credit for line in lines)
    return dr == cr
