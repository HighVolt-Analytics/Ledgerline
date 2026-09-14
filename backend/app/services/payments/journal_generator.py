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
    ROUTE_TEAM,
    get_payable_account_mapping,
    get_tax_account_mapping,
    get_team_settlement_account_mapping,
    resolve_sales_post_accounts,
    team_settlement_account_label,
)
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_DIRECT,
    normalize_team_expense_kind,
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
    txn_currency: str | None = None
    base_currency: str | None = None
    base_debit: Decimal | None = None
    base_credit: Decimal | None = None
    fx_rate: Decimal | None = None
    fx_source: str | None = None


def _with_accrual_fx(
    lines: list[JournalLine],
    *,
    invoice: Invoice,
    base_currency: str | None = None,
) -> list[JournalLine]:
    from app.services.payments.journal_fx import (
        apply_line_fx,
        invoice_currency_code,
        resolve_accrual_fx,
    )

    txn = invoice_currency_code(invoice)
    base = (base_currency or "").strip().upper()
    rate, _, source = resolve_accrual_fx(txn_currency=txn, base_currency=base)
    enriched: list[JournalLine] = []
    for line in lines:
        fields = apply_line_fx(
            debit=line.debit,
            credit=line.credit,
            txn_currency=txn,
            base_currency=base,
            fx_rate=rate,
            fx_source=source,
        )
        enriched.append(
            JournalLine(
                date=line.date,
                account_code=line.account_code,
                account_name=line.account_name,
                debit=line.debit,
                credit=line.credit,
                entry_type=line.entry_type,
                vendor_registry_id=line.vendor_registry_id,
                customer_registry_id=line.customer_registry_id,
                txn_currency=fields["txn_currency"],  # type: ignore[arg-type]
                base_currency=fields["base_currency"],  # type: ignore[arg-type]
                base_debit=fields["base_debit"],  # type: ignore[arg-type]
                base_credit=fields["base_credit"],  # type: ignore[arg-type]
                fx_rate=fields["fx_rate"],  # type: ignore[arg-type]
                fx_source=fields["fx_source"],  # type: ignore[arg-type]
            )
        )
    return enriched


def resolve_team_advance_parent_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    """Org default advance parent (tenant-selected COA ledger) when an employee child is unavailable."""
    label = (config.team_expense_posting.default_advance_parent_ledger or "").strip()
    return resolve_category_for_config(label, config)


def claim_advance_net_amount(
    claim_total: Decimal,
    advance_available: Decimal | None,
) -> Decimal:
    """How much Staff Advance float to clear on an expense claim (partial netting OK)."""
    total = _quantize_money(max(Decimal("0"), claim_total))
    available = _quantize_money(max(Decimal("0"), advance_available or Decimal("0")))
    return min(total, available)


def _team_expense_entries(
    invoice: Invoice,
    mapping: AccountMapping,
    config: RuleBookConfigPayload,
    *,
    entry_date: date,
    subtotal: Decimal,
    gst: Decimal,
    total: Decimal,
    control_mapping: AccountMapping | None,
    advance_available: Decimal | None = None,
) -> list[JournalLine]:
    """
    Team Expenses journals keyed by claim kind.

    Advance requisition  Dr employee advance / Cr settlement
    Expense claim        Dr expense (+ tax) / Cr advance (net available) + Cr settlement (rest)
    """
    kind = normalize_team_expense_kind(invoice.team_expense_kind)
    settlement = get_team_settlement_account_mapping(config)
    advance = _team_advance_debit_mapping(
        invoice, mapping, config, control_mapping
    )

    if kind == TEAM_EXPENSE_KIND_ADVANCE:
        return [
            JournalLine(
                entry_date,
                advance.account_code,
                advance.account_name,
                total,
                Decimal("0"),
                EntryType.DEBIT,
            ),
            JournalLine(
                entry_date,
                settlement.account_code,
                settlement.account_name,
                Decimal("0"),
                total,
                EntryType.CREDIT,
            ),
        ]

    lines = [
        JournalLine(
            entry_date,
            mapping.account_code,
            mapping.account_name,
            subtotal,
            Decimal("0"),
            EntryType.DEBIT,
        )
    ]
    if gst != Decimal("0"):
        tax = get_tax_account_mapping(config)
        lines.append(
            JournalLine(
                entry_date,
                tax.account_code,
                tax.account_name,
                gst,
                Decimal("0"),
                EntryType.DEBIT,
            )
        )

    net_advance = claim_advance_net_amount(total, advance_available)
    if kind == TEAM_EXPENSE_KIND_DIRECT:
        from app.services.purchase.team_expense_advance_service import (
            claim_wants_advance_netting,
        )

        if not claim_wants_advance_netting(
            cost_centre=getattr(invoice, "cost_centre", None),
            billing_address=getattr(invoice, "billing_address", None),
        ):
            net_advance = Decimal("0")
    settle_credit = _quantize_money(total - net_advance)
    if net_advance > 0:
        lines.append(
            JournalLine(
                entry_date,
                advance.account_code,
                advance.account_name,
                Decimal("0"),
                net_advance,
                EntryType.CREDIT,
            )
        )
    if settle_credit > 0:
        lines.append(
            JournalLine(
                entry_date,
                settlement.account_code,
                settlement.account_name,
                Decimal("0"),
                settle_credit,
                EntryType.CREDIT,
            )
        )
    return lines


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _line_effective_amount_groups(
    invoice: Invoice,
    *,
    parent_ledger: str,
    header_subtotal: Decimal,
) -> list[tuple[str, Decimal]]:
    """Group line net amounts by effective ledger; residual to parent when needed."""
    from sqlalchemy import inspect as sa_inspect

    from app.services.invoice.line_item_gl_service import effective_line_ledger

    # generate_entries is sync — never trigger async lazy-load of line_items.
    state = sa_inspect(invoice)
    if state is not None and "line_items" in state.unloaded:
        line_items: list = []
    else:
        line_items = list(getattr(invoice, "line_items", None) or [])

    parent = (parent_ledger or "").strip()
    amounts: dict[str, Decimal] = {}
    ordered: list[str] = []
    for line in line_items:
        raw = getattr(line, "amount", None)
        if raw is None:
            continue
        try:
            amount = _quantize_money(Decimal(str(raw)))
        except Exception:
            continue
        if amount == 0:
            continue
        line_parent = (getattr(line, "parent_ledger", None) or "").strip() or parent
        name = effective_line_ledger(
            sub_ledger=getattr(line, "sub_ledger", None),
            parent_ledger=line_parent,
        )
        if not name:
            name = parent
        if name not in amounts:
            ordered.append(name)
            amounts[name] = Decimal("0.00")
        amounts[name] = _quantize_money(amounts[name] + amount)

    if not amounts:
        return [(parent, _quantize_money(header_subtotal))] if parent else []

    line_sum = _quantize_money(sum(amounts.values(), Decimal("0.00")))
    residual = _quantize_money(_quantize_money(header_subtotal) - line_sum)
    if residual != 0 and parent:
        if parent not in amounts:
            ordered.append(parent)
            amounts[parent] = Decimal("0.00")
        amounts[parent] = _quantize_money(amounts[parent] + residual)

    return [(name, amounts[name]) for name in ordered if amounts[name] != 0]


def _journal_legs_for_effective_ledgers(
    *,
    entry_date: date,
    invoice: Invoice,
    mapping: AccountMapping,
    config: RuleBookConfigPayload,
    header_subtotal: Decimal,
    debit: bool,
) -> list[JournalLine]:
    parent_name = (mapping.account_name or "").strip()
    groups = _line_effective_amount_groups(
        invoice,
        parent_ledger=parent_name,
        header_subtotal=header_subtotal,
    )
    if not groups:
        if debit:
            return [
                JournalLine(
                    entry_date,
                    mapping.account_code,
                    mapping.account_name,
                    header_subtotal,
                    Decimal("0"),
                    EntryType.DEBIT,
                )
            ]
        return [
            JournalLine(
                entry_date,
                mapping.account_code,
                mapping.account_name,
                Decimal("0"),
                header_subtotal,
                EntryType.CREDIT,
            )
        ]

    legs: list[JournalLine] = []
    for ledger_name, amount in groups:
        from app.services.invoice.line_item_gl_service import resolve_effective_ledger_mapping

        if ledger_name.strip().lower() == parent_name.lower():
            resolved = mapping
        else:
            resolved = resolve_effective_ledger_mapping(
                parent_ledger=parent_name,
                effective_ledger=ledger_name,
                config=config,
            )
        if debit:
            legs.append(
                JournalLine(
                    entry_date,
                    resolved.account_code,
                    resolved.account_name,
                    amount,
                    Decimal("0"),
                    EntryType.DEBIT,
                )
            )
        else:
            legs.append(
                JournalLine(
                    entry_date,
                    resolved.account_code,
                    resolved.account_name,
                    Decimal("0"),
                    amount,
                    EntryType.CREDIT,
                )
            )
    return legs


def generate_entries(
    invoice: Invoice,
    mapping: AccountMapping,
    *,
    config: RuleBookConfigPayload | None = None,
    sales_order=None,
    vendor_registry_id: int | None = None,
    customer_registry_id: int | None = None,
    control_mapping: AccountMapping | None = None,
    base_currency: str | None = None,
    advance_available: Decimal | None = None,
) -> list[JournalLine]:
    from app.schemas.rule_book_config import RuleBookConfigPayload as ConfigPayload

    cfg = config or ConfigPayload()
    if invoice.invoice_date is None:
        return []
    entry_date = invoice.invoice_date
    subtotal, gst, total = resolve_invoice_amounts(invoice)

    if (invoice.route_target or "").strip() == ROUTE_TEAM:
        lines = _team_expense_entries(
            invoice,
            mapping,
            cfg,
            entry_date=entry_date,
            subtotal=subtotal,
            gst=gst,
            total=total,
            control_mapping=control_mapping,
            advance_available=advance_available,
        )
        return _with_accrual_fx(lines, invoice=invoice, base_currency=base_currency)

    if (invoice.route_target or "").strip() == ROUTE_SALES:
        recv_label, tax_label = resolve_sales_post_accounts(
            invoice,
            cfg,
            sales_order=sales_order,
        )
        receivable = control_mapping or resolve_category_for_config(recv_label, cfg)
        tax = resolve_category_for_config(tax_label, cfg)
        revenue_legs = _journal_legs_for_effective_ledgers(
            entry_date=entry_date,
            invoice=invoice,
            mapping=mapping,
            config=cfg,
            header_subtotal=subtotal,
            debit=False,
        )
        lines = [
            JournalLine(
                entry_date,
                receivable.account_code,
                receivable.account_name,
                total,
                Decimal("0"),
                EntryType.DEBIT,
                customer_registry_id=customer_registry_id,
            ),
            *revenue_legs,
            JournalLine(
                entry_date,
                tax.account_code,
                tax.account_name,
                Decimal("0"),
                gst,
                EntryType.CREDIT,
            ),
        ]
        return _with_accrual_fx(lines, invoice=invoice, base_currency=base_currency)

    tax = get_tax_account_mapping(cfg)
    payable = control_mapping or get_payable_account_mapping(cfg)
    expense_legs = _journal_legs_for_effective_ledgers(
        entry_date=entry_date,
        invoice=invoice,
        mapping=mapping,
        config=cfg,
        header_subtotal=subtotal,
        debit=True,
    )

    lines = [
        *expense_legs,
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
    return _with_accrual_fx(lines, invoice=invoice, base_currency=base_currency)



def is_balanced(lines: list[JournalLine]) -> bool:
    dr = sum(line.debit for line in lines)
    cr = sum(line.credit for line in lines)
    return dr == cr


def _is_usable_control_mapping(mapping: AccountMapping | None) -> bool:
    if mapping is None:
        return False
    code = (mapping.account_code or "").strip()
    name = (mapping.account_name or "").strip()
    if not code:
        return False
    token = f"{name} {code}".lower()
    if code == "9999" or "suspense" in token or "unmapped" in token:
        return False
    return True


def _invoice_has_team_advance_ledger(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    """True when the invoice already maps a usable employee advance ledger."""
    code = (invoice.account_code or "").strip()
    name = (invoice.account_name or "").strip()
    if not code:
        return False
    token = f"{name} {code}".lower()
    if "suspense" in token or "unmapped" in token:
        return False
    if code.upper().startswith("EM-"):
        return True
    for entry in config.chart_of_accounts or []:
        if (entry.code or "").strip() == code:
            return True
        for sub in entry.sub_ledgers or []:
            if (sub.code or "").strip() == code:
                return True
    return False


def _team_advance_debit_mapping(
    invoice: Invoice,
    mapping: AccountMapping,
    config: RuleBookConfigPayload,
    control_mapping: AccountMapping | None,
) -> AccountMapping:
    """Employee advance line: party child, else invoice EM- ledger, else parent."""
    if _is_usable_control_mapping(control_mapping):
        return control_mapping
    if _invoice_has_team_advance_ledger(invoice, config):
        code = (invoice.account_code or "").strip()
        name = (invoice.account_name or "").strip() or code
        return AccountMapping(code, name)
    if _is_usable_control_mapping(mapping) and (mapping.account_code or "").upper().startswith(
        "EM-"
    ):
        return mapping
    return resolve_team_advance_parent_mapping(config)


def get_unresolved_control_accounts(
    *,
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> list[ControlAccountRole]:
    """Return control/tax roles whose COA labels are missing from the tenant chart.

    Includes the fallback/suspense account itself: header and line GL mapping
    silently degrade to it whenever a category can't be classified, so if
    *that* label isn't in the tenant's own chart either, resolve_category_for_config
    has nowhere safe to park the entry (see account_mapper.py) and this must
    halt posting rather than let an empty/unresolved account code through.
    """
    unresolved: list[ControlAccountRole] = []
    if not category_resolved_in_coa(config.posting_defaults.fallback_account, config):
        unresolved.append("fallback_account")

    if (invoice.route_target or "").strip() == ROUTE_SALES:
        recv_label, tax_label = resolve_sales_post_accounts(invoice, config)
        if not category_resolved_in_coa(recv_label, config):
            unresolved.append("receivable_account")
        if not category_resolved_in_coa(tax_label, config):
            unresolved.append("tax_account")
        return unresolved

    if (invoice.route_target or "").strip() == ROUTE_TEAM:
        team = config.team_expense_posting
        kind = normalize_team_expense_kind(invoice.team_expense_kind)
        settlement_label = team_settlement_account_label(config)
        # Settlement always; Staff Advance needed for requisitions and claim netting.
        if not category_resolved_in_coa(settlement_label, config):
            unresolved.append("settlement_account")
        parent_ok = category_resolved_in_coa(
            team.default_advance_parent_ledger, config
        )
        # Advance requisitions already debit the employee child (EM-…). Do not
        # halt posting solely because the parent Staff Advance label is absent.
        if kind == TEAM_EXPENSE_KIND_ADVANCE:
            if not parent_ok and not _invoice_has_team_advance_ledger(invoice, config):
                unresolved.append("staff_advance_account")
        elif kind != TEAM_EXPENSE_KIND_DIRECT and not parent_ok:
            unresolved.append("staff_advance_account")
        if kind not in {TEAM_EXPENSE_KIND_ADVANCE} and not category_resolved_in_coa(
            config.posting_defaults.tax_account, config
        ):
            unresolved.append("tax_account")
        return unresolved

    defaults = config.posting_defaults
    if not category_resolved_in_coa(defaults.payable_account, config):
        unresolved.append("payable_account")
    if not category_resolved_in_coa(defaults.tax_account, config):
        unresolved.append("tax_account")
    return unresolved
