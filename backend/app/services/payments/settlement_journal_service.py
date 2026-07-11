"""Settlement journal line generation for payment and collection events."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.collection import Collection
from app.models.invoice import Invoice
from app.models.journal import EntryType
from app.models.payment import Payment
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.payments.journal_generator import JournalLine
from app.services.rule_book.account_mapper import AccountMapping
from app.services.rule_book.rule_book_mapper import (
    get_bank_account_mapping,
    get_payable_account_mapping,
    get_receivable_account_mapping,
)


def _settlement_date(value) -> date:
    if value is None:
        return date.today()
    if hasattr(value, "date"):
        return value.date()
    return value


def generate_payment_settlement_entries(
    payment: Payment,
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    control_mapping: AccountMapping | None = None,
    vendor_registry_id: int | None = None,
) -> list[JournalLine]:
    payable = control_mapping or get_payable_account_mapping(config)
    bank = get_bank_account_mapping(config)
    entry_date = _settlement_date(payment.paid_date)
    amount = payment.amount
    vendor_id = vendor_registry_id if vendor_registry_id is not None else payment.vendor_registry_id

    return [
        JournalLine(
            entry_date,
            payable.account_code,
            payable.account_name,
            amount,
            Decimal("0"),
            EntryType.DEBIT,
            vendor_registry_id=vendor_id,
        ),
        JournalLine(
            entry_date,
            bank.account_code,
            bank.account_name,
            Decimal("0"),
            amount,
            EntryType.CREDIT,
        ),
    ]


def generate_collection_settlement_entries(
    collection: Collection,
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    control_mapping: AccountMapping | None = None,
    customer_registry_id: int | None = None,
) -> list[JournalLine]:
    bank = get_bank_account_mapping(config)
    receivable = control_mapping or get_receivable_account_mapping(config)
    entry_date = _settlement_date(collection.received_date)
    amount = collection.amount
    customer_id = (
        customer_registry_id
        if customer_registry_id is not None
        else collection.customer_registry_id
    )

    return [
        JournalLine(
            entry_date,
            bank.account_code,
            bank.account_name,
            amount,
            Decimal("0"),
            EntryType.DEBIT,
        ),
        JournalLine(
            entry_date,
            receivable.account_code,
            receivable.account_name,
            Decimal("0"),
            amount,
            EntryType.CREDIT,
            customer_registry_id=customer_id,
        ),
    ]
