from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice
from app.models.journal import EntryType
from app.services.account_mapper import AccountMapping
from app.services.rule_book_mapper import (
    get_payable_account_mapping,
    get_tax_account_mapping,
)


@dataclass
class JournalLine:
    date: date
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    entry_type: EntryType


def generate_entries(invoice: Invoice, mapping: AccountMapping) -> list[JournalLine]:
    entry_date = invoice.invoice_date or date.today()
    subtotal = invoice.subtotal or Decimal("0")
    gst = invoice.gst or Decimal("0")
    total = invoice.total or subtotal + gst
    tax = get_tax_account_mapping(invoice.org_id)
    payable = get_payable_account_mapping(invoice.org_id)

    return [
        JournalLine(
            entry_date,
            mapping.account_code,
            mapping.account_name,
            subtotal,
            Decimal("0"),
            EntryType.DEBIT,
        ),
        JournalLine(
            entry_date,
            tax.account_code,
            tax.account_name,
            gst,
            Decimal("0"),
            EntryType.DEBIT,
        ),
        JournalLine(
            entry_date,
            payable.account_code,
            payable.account_name,
            Decimal("0"),
            total,
            EntryType.CREDIT,
        ),
    ]


def is_balanced(lines: list[JournalLine]) -> bool:
    dr = sum(line.debit for line in lines)
    cr = sum(line.credit for line in lines)
    return dr == cr
