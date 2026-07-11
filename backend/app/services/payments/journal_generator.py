from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice
from app.models.journal import EntryType
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.rule_book.account_mapper import (
    AccountMapping,
    ControlAccountRole,
    category_resolved_in_coa,
    resolve_category_for_config,
)
from app.services.invoice.invoice_amounts import resolve_invoice_amounts
from app.services.rule_book.rule_book_mapper import (
    ROUTE_SALES,
    get_payable_account_mapping,
    get_tax_account_mapping,
    resolve_sales_post_accounts,
)


@dataclass
class JournalLine:
    date: date
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    entry_type: EntryType
    vendor_registry_id: int | None = None
    customer_registry_id: int | None = None


def generate_entries(
    invoice: Invoice,
    mapping: AccountMapping,
    *,
    config: RuleBookConfigPayload | None = None,
    sales_order=None,
    vendor_registry_id: int | None = None,
    customer_registry_id: int | None = None,
    control_mapping: AccountMapping | None = None,
) -> list[JournalLine]:
    from app.schemas.rule_book_config import RuleBookConfigPayload as ConfigPayload

    cfg = config or ConfigPayload()
    entry_date = invoice.invoice_date or date.today()
    subtotal, gst, total = resolve_invoice_amounts(invoice)

    if (invoice.route_target or "").strip() == ROUTE_SALES:
        recv_label, tax_label = resolve_sales_post_accounts(
            invoice,
            cfg,
            sales_order=sales_order,
        )
        receivable = control_mapping or resolve_category_for_config(recv_label, cfg)
        tax = resolve_category_for_config(tax_label, cfg)
        return [
            JournalLine(
                entry_date,
                receivable.account_code,
                receivable.account_name,
                total,
                Decimal("0"),
                EntryType.DEBIT,
                customer_registry_id=customer_registry_id,
            ),
            JournalLine(
                entry_date,
                mapping.account_code,
                mapping.account_name,
                Decimal("0"),
                subtotal,
                EntryType.CREDIT,
            ),
            JournalLine(
                entry_date,
                tax.account_code,
                tax.account_name,
                Decimal("0"),
                gst,
                EntryType.CREDIT,
            ),
        ]

    tax = get_tax_account_mapping(cfg)
    payable = control_mapping or get_payable_account_mapping(cfg)

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
            vendor_registry_id=vendor_registry_id,
        ),
    ]


def is_balanced(lines: list[JournalLine]) -> bool:
    dr = sum(line.debit for line in lines)
    cr = sum(line.credit for line in lines)
    return dr == cr


def get_unresolved_control_accounts(
    *,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> list[ControlAccountRole]:
    """Return control/tax roles whose COA labels are missing from the tenant chart."""
    unresolved: list[ControlAccountRole] = []

    if (invoice.route_target or "").strip() == ROUTE_SALES:
        recv_label, tax_label = resolve_sales_post_accounts(invoice, config)
        if not category_resolved_in_coa(recv_label, config):
            unresolved.append("receivable_account")
        if not category_resolved_in_coa(tax_label, config):
            unresolved.append("tax_account")
        return unresolved

    defaults = config.posting_defaults
    if not category_resolved_in_coa(defaults.payable_account, config):
        unresolved.append("payable_account")
    if not category_resolved_in_coa(defaults.tax_account, config):
        unresolved.append("tax_account")
    return unresolved
