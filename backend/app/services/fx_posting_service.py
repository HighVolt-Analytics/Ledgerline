"""FX booking at invoice date and gain/loss at payment."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.invoice import Invoice
from app.models.journal import EntryType
from app.schemas.fx_posting import FxPostingPolicy
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.currency import BASE_CURRENCY, fx_rate_to_base
from app.services.journal_generator import JournalLine


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_fx_policy(
    *,
    config: RuleBookConfigPayload,
    document_type_code: str | None = None,
) -> FxPostingPolicy:
    from app.services.document_type_catalog import get_document_type_definition

    if document_type_code:
        definition = get_document_type_definition(
            document_type_code,
            document_types=config.document_types,
        )
        if definition is not None:
            policy = getattr(definition, "fx_policy", None)
            if policy is not None:
                return policy
    defaults = config.posting_defaults
    return FxPostingPolicy(
        functional_currency=defaults.functional_currency or BASE_CURRENCY,
        fx_gain_loss_account=defaults.fx_gain_loss_account or "FX Gain/Loss",
        bank_account=defaults.bank_account or "Bank",
    )


def booking_fx_rate(
    document_currency: str | None,
    *,
    functional_currency: str,
    on_date: date | None = None,
) -> Decimal:
    """Rate: 1 unit of document currency = X units of functional currency."""
    doc = (document_currency or functional_currency).upper()
    func = functional_currency.upper()
    if doc == func:
        return Decimal("1")
    # Static table: rates are defined as doc → AUD (functional when AUD).
    if func == BASE_CURRENCY:
        return fx_rate_to_base(doc)
    if doc == BASE_CURRENCY:
        base_to_func = fx_rate_to_base(func)
        if base_to_func <= 0:
            return Decimal("1")
        return Decimal("1") / base_to_func
    return fx_rate_to_base(doc)


def document_to_functional(
    amount: Decimal | None,
    document_currency: str | None,
    *,
    policy: FxPostingPolicy,
    booking_date: date | None = None,
) -> tuple[Decimal, Decimal]:
    """Return (functional_amount, fx_rate_used)."""
    raw = Decimal(str(amount or 0))
    rate = booking_fx_rate(
        document_currency,
        functional_currency=policy.functional_currency,
        on_date=booking_date,
    )
    return _money(raw * rate), rate


def generate_booking_entries(
    invoice: Invoice,
    mapping,
    *,
    config: RuleBookConfigPayload,
    policy: FxPostingPolicy | None = None,
    sales_order=None,
) -> list[JournalLine]:
    """Invoice accrual in functional currency; stores rate on invoice when foreign."""
    from app.services.account_mapper import AccountMapping, resolve_category_for_config
    from app.services.rule_book_mapper import (
        ROUTE_SALES,
        get_payable_account_mapping,
        get_tax_account_mapping,
        resolve_sales_post_accounts,
    )

    if not isinstance(mapping, AccountMapping):
        raise TypeError("mapping must be AccountMapping")

    fx = policy or resolve_fx_policy(
        config=config,
        document_type_code=invoice.document_type_code,
    )
    entry_date = invoice.invoice_date or date.today()
    doc_currency = (invoice.currency or fx.functional_currency).upper()
    subtotal = invoice.subtotal or Decimal("0")
    gst = invoice.gst or Decimal("0")
    total = invoice.total or subtotal + gst

    subtotal_fn, rate = document_to_functional(
        subtotal, doc_currency, policy=fx, booking_date=entry_date
    )
    gst_fn, _ = document_to_functional(gst, doc_currency, policy=fx, booking_date=entry_date)
    total_fn, _ = document_to_functional(total, doc_currency, policy=fx, booking_date=entry_date)

    invoice.booking_fx_rate = rate if doc_currency != fx.functional_currency.upper() else None
    invoice.functional_currency = fx.functional_currency
    invoice.functional_total = total_fn

    if (invoice.route_target or "").strip() == ROUTE_SALES:
        recv_label, tax_label = resolve_sales_post_accounts(
            invoice,
            config,
            sales_order=sales_order,
        )
        receivable = resolve_category_for_config(recv_label, config)
        tax = resolve_category_for_config(tax_label, config)
        return [
            JournalLine(
                entry_date,
                receivable.account_code,
                receivable.account_name,
                total_fn,
                Decimal("0"),
                EntryType.DEBIT,
            ),
            JournalLine(
                entry_date,
                mapping.account_code,
                mapping.account_name,
                Decimal("0"),
                subtotal_fn,
                EntryType.CREDIT,
            ),
            JournalLine(
                entry_date,
                tax.account_code,
                tax.account_name,
                Decimal("0"),
                gst_fn,
                EntryType.CREDIT,
            ),
        ]

    tax = get_tax_account_mapping(config)
    payable = get_payable_account_mapping(config)

    return [
        JournalLine(
            entry_date,
            mapping.account_code,
            mapping.account_name,
            subtotal_fn,
            Decimal("0"),
            EntryType.DEBIT,
        ),
        JournalLine(
            entry_date,
            tax.account_code,
            tax.account_name,
            gst_fn,
            Decimal("0"),
            EntryType.DEBIT,
        ),
        JournalLine(
            entry_date,
            payable.account_code,
            payable.account_name,
            Decimal("0"),
            total_fn,
            EntryType.CREDIT,
        ),
    ]


def generate_payment_entries(
    *,
    functional_ap_amount: Decimal,
    bank_payment_amount: Decimal,
    policy: FxPostingPolicy,
    payable_account_code: str,
    payable_account_name: str,
    payment_date: date,
) -> tuple[list[JournalLine], Decimal]:
    """
    Clear AP at booked functional amount; pay bank in payment currency (typically functional).
    FX variance → fx_gain_loss_account.
    """
    ap = _money(functional_ap_amount)
    bank = _money(bank_payment_amount)
    variance = _money(bank - ap)
    lines: list[JournalLine] = [
        JournalLine(
            payment_date,
            payable_account_code,
            payable_account_name,
            ap,
            Decimal("0"),
            EntryType.DEBIT,
        ),
    ]
    if variance != 0:
        if variance > 0:
            lines.append(
                JournalLine(
                    payment_date,
                    "fx-gl",
                    policy.fx_gain_loss_account,
                    variance,
                    Decimal("0"),
                    EntryType.DEBIT,
                )
            )
        else:
            lines.append(
                JournalLine(
                    payment_date,
                    "fx-gl",
                    policy.fx_gain_loss_account,
                    Decimal("0"),
                    abs(variance),
                    EntryType.CREDIT,
                )
            )
    lines.append(
        JournalLine(
            payment_date,
            "bank",
            policy.bank_account,
            Decimal("0"),
            bank,
            EntryType.CREDIT,
        )
    )
    return lines, variance


def po_invoice_currency_mismatch(
    po_currency: str | None,
    invoice_currency: str | None,
    *,
    policy: FxPostingPolicy,
) -> bool:
    if not policy.require_po_invoice_currency_match:
        return False
    po = (po_currency or policy.functional_currency).upper()
    inv = (invoice_currency or policy.functional_currency).upper()
    return po != inv
