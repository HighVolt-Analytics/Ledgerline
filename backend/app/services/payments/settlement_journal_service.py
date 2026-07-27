"""Settlement journal line generation for payment and collection events."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.collection import Collection
from app.models.invoice import Invoice
from app.models.journal import EntryType
from app.models.payment import Payment
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.payments.journal_fx import (
    FX_SOURCE_PENDING_PAYMENT,
    apply_line_fx,
    invoice_currency_code,
    resolve_payment_fx,
    round_money,
)
from app.services.payments.journal_generator import JournalLine
from app.services.rule_book.account_mapper import AccountMapping, resolve_category_for_config
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


def _fx_account(config: RuleBookConfigPayload) -> AccountMapping:
    label = getattr(config.posting_defaults, "fx_account", None) or "FX Gain/Loss"
    return resolve_category_for_config(label, config)


def generate_payment_settlement_entries(
    payment: Payment,
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    control_mapping: AccountMapping | None = None,
    vendor_registry_id: int | None = None,
    base_currency: str | None = None,
) -> list[JournalLine]:
    payable = control_mapping or get_payable_account_mapping(config)
    bank = get_bank_account_mapping(config)
    entry_date = _settlement_date(payment.paid_date)
    amount = Decimal(str(payment.amount or 0))
    vendor_id = vendor_registry_id if vendor_registry_id is not None else payment.vendor_registry_id
    txn_currency = invoice_currency_code(invoice) if not (payment.currency or "").strip() else (
        (payment.currency or "").strip().upper()
    )
    base = (base_currency or "").strip().upper()

    rate, bank_base, variance, fx_source = resolve_payment_fx(
        payment,
        base_currency=base,
    )

    # Keep settlement in transaction currency until payment-app rate is available.
    if fx_source == FX_SOURCE_PENDING_PAYMENT or rate is None or bank_base is None:
        fields = apply_line_fx(
            debit=amount,
            credit=Decimal("0"),
            txn_currency=txn_currency,
            base_currency=base,
            fx_rate=None,
            fx_source=FX_SOURCE_PENDING_PAYMENT,
        )
        return [
            JournalLine(
                entry_date,
                payable.account_code,
                payable.account_name,
                amount,
                Decimal("0"),
                EntryType.DEBIT,
                vendor_registry_id=vendor_id,
                txn_currency=fields["txn_currency"],  # type: ignore[arg-type]
                base_currency=fields["base_currency"],  # type: ignore[arg-type]
                base_debit=fields["base_debit"],  # type: ignore[arg-type]
                base_credit=fields["base_credit"],  # type: ignore[arg-type]
                fx_rate=fields["fx_rate"],  # type: ignore[arg-type]
                fx_source=fields["fx_source"],  # type: ignore[arg-type]
            ),
            JournalLine(
                entry_date,
                bank.account_code,
                bank.account_name,
                Decimal("0"),
                amount,
                EntryType.CREDIT,
                txn_currency=fields["txn_currency"],  # type: ignore[arg-type]
                base_currency=fields["base_currency"],  # type: ignore[arg-type]
                base_debit=Decimal("0.00"),
                base_credit=fields["base_debit"],  # type: ignore[arg-type]
                fx_rate=fields["fx_rate"],  # type: ignore[arg-type]
                fx_source=fields["fx_source"],  # type: ignore[arg-type]
            ),
        ]

    # Payment-app conversion: post settlement in base currency, retain txn audit fields.
    settle_base = round_money(bank_base)
    ap_fields = apply_line_fx(
        debit=amount,
        credit=Decimal("0"),
        txn_currency=txn_currency,
        base_currency=base,
        fx_rate=rate,
        fx_source=fx_source,
    )
    # Override base amounts with explicit bank settlement amount.
    ap_fields["base_debit"] = settle_base
    ap_fields["base_credit"] = Decimal("0.00")

    lines = [
        JournalLine(
            entry_date,
            payable.account_code,
            payable.account_name,
            # Functional settlement amount used for ledger balancing when converted.
            settle_base,
            Decimal("0"),
            EntryType.DEBIT,
            vendor_registry_id=vendor_id,
            txn_currency=txn_currency,
            base_currency=base or None,
            base_debit=settle_base,
            base_credit=Decimal("0.00"),
            fx_rate=rate,
            fx_source=fx_source,
        ),
        JournalLine(
            entry_date,
            bank.account_code,
            bank.account_name,
            Decimal("0"),
            settle_base,
            EntryType.CREDIT,
            txn_currency=txn_currency,
            base_currency=base or None,
            base_debit=Decimal("0.00"),
            base_credit=settle_base,
            fx_rate=rate,
            fx_source=fx_source,
        ),
    ]

    # Optional realized FX variance vs amount*rate (payment app true cash).
    if variance is not None and variance != 0:
        fx_acct = _fx_account(config)
        abs_var = round_money(abs(variance))
        if variance > 0:
            # Paid more base than rate implies → FX loss (debit).
            lines.append(
                JournalLine(
                    entry_date,
                    fx_acct.account_code,
                    fx_acct.account_name,
                    abs_var,
                    Decimal("0"),
                    EntryType.DEBIT,
                    txn_currency=txn_currency,
                    base_currency=base or None,
                    base_debit=abs_var,
                    base_credit=Decimal("0.00"),
                    fx_rate=rate,
                    fx_source=fx_source,
                )
            )
            lines.append(
                JournalLine(
                    entry_date,
                    bank.account_code,
                    bank.account_name,
                    Decimal("0"),
                    abs_var,
                    EntryType.CREDIT,
                    txn_currency=txn_currency,
                    base_currency=base or None,
                    base_debit=Decimal("0.00"),
                    base_credit=abs_var,
                    fx_rate=rate,
                    fx_source=fx_source,
                )
            )
        else:
            # Paid less → FX gain (credit).
            lines.append(
                JournalLine(
                    entry_date,
                    bank.account_code,
                    bank.account_name,
                    abs_var,
                    Decimal("0"),
                    EntryType.DEBIT,
                    txn_currency=txn_currency,
                    base_currency=base or None,
                    base_debit=abs_var,
                    base_credit=Decimal("0.00"),
                    fx_rate=rate,
                    fx_source=fx_source,
                )
            )
            lines.append(
                JournalLine(
                    entry_date,
                    fx_acct.account_code,
                    fx_acct.account_name,
                    Decimal("0"),
                    abs_var,
                    EntryType.CREDIT,
                    txn_currency=txn_currency,
                    base_currency=base or None,
                    base_debit=Decimal("0.00"),
                    base_credit=abs_var,
                    fx_rate=rate,
                    fx_source=fx_source,
                )
            )

    _ = ap_fields  # retained for clarity / future txn-amount journal columns
    return lines


def generate_collection_settlement_entries(
    collection: Collection,
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    control_mapping: AccountMapping | None = None,
    customer_registry_id: int | None = None,
    base_currency: str | None = None,
) -> list[JournalLine]:
    bank = get_bank_account_mapping(config)
    receivable = control_mapping or get_receivable_account_mapping(config)
    entry_date = _settlement_date(collection.received_date)
    amount = Decimal(str(collection.amount or 0))
    customer_id = (
        customer_registry_id
        if customer_registry_id is not None
        else collection.customer_registry_id
    )
    txn_currency = invoice_currency_code(invoice)
    base = (base_currency or "").strip().upper()
    fields = apply_line_fx(
        debit=amount,
        credit=Decimal("0"),
        txn_currency=txn_currency,
        base_currency=base,
        fx_rate=Decimal("1") if txn_currency == base and base else None,
        fx_source="identity" if txn_currency == base and base else FX_SOURCE_PENDING_PAYMENT,
    )

    return [
        JournalLine(
            entry_date,
            bank.account_code,
            bank.account_name,
            amount,
            Decimal("0"),
            EntryType.DEBIT,
            txn_currency=fields["txn_currency"],  # type: ignore[arg-type]
            base_currency=fields["base_currency"],  # type: ignore[arg-type]
            base_debit=fields["base_debit"],  # type: ignore[arg-type]
            base_credit=fields["base_credit"],  # type: ignore[arg-type]
            fx_rate=fields["fx_rate"],  # type: ignore[arg-type]
            fx_source=fields["fx_source"],  # type: ignore[arg-type]
        ),
        JournalLine(
            entry_date,
            receivable.account_code,
            receivable.account_name,
            Decimal("0"),
            amount,
            EntryType.CREDIT,
            customer_registry_id=customer_id,
            txn_currency=fields["txn_currency"],  # type: ignore[arg-type]
            base_currency=fields["base_currency"],  # type: ignore[arg-type]
            base_debit=Decimal("0.00"),
            base_credit=fields["base_debit"],  # type: ignore[arg-type]
            fx_rate=fields["fx_rate"],  # type: ignore[arg-type]
            fx_source=fields["fx_source"],  # type: ignore[arg-type]
        ),
    ]
