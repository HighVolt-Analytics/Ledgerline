"""Map invoices using the unified classification rule book."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.account_mapper import AccountMapping, MappingDetail, resolve_category_for_config
from app.services.capture_channel import is_staff_claim_sender
from app.services.rule_book_config_io import load_rule_book_config_with_masters
from app.services.rule_book_evaluate_service import invoice_to_eval_document

ROUTE_PURCHASE = "Purchase Management"
ROUTE_EXPENSES = "Expenses Management"
ROUTE_TEAM = "Team Expenses"
ROUTE_VAULT = "Vault"
from app.services.legacy_cascade import legacy_rule_type, match_legacy_cascade
from app.services.rule_engine import (
    match_expense_rule,
    match_purchase_rule,
    match_team_expense_rule,
)

def _invoice_amount(invoice: Invoice) -> float | None:
    if invoice.total is None:
        return None
    return float(invoice.total)


FALLBACK_RULE_TYPE = "Fallback"


@dataclass(frozen=True)
class ConfigMappingHit:
    mapping: AccountMapping
    rule_type: str
    match_reason: str


async def load_classification_config(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> RuleBookConfigPayload:
    raw = await load_rule_book_config_with_masters(session, tenant_id)
    return validate_rule_book_config_payload(raw)


def clear_classification_config_cache() -> None:
    from app.services.document_type_catalog import clear_document_type_catalog_cache
    from app.services.rule_book_config_io import clear_posting_config_cache

    clear_document_type_catalog_cache()
    clear_posting_config_cache()


def _ledger_to_mapping(ledger: str, config: RuleBookConfigPayload) -> AccountMapping:
    resolved = resolve_category_for_config(ledger, config)
    return AccountMapping(
        account_code=resolved.account_code,
        account_name=resolved.account_name,
        expense_category=ledger,
    )


def mapping_hit_from_po(
    po: PurchaseOrder,
    config: RuleBookConfigPayload,
) -> ConfigMappingHit | None:
    """Coding inheritance — PO ledger applied to linked invoice (architecture §4)."""
    ledger = (po.ledger or "").strip()
    if not ledger:
        return None
    sub = (po.sub_ledger or "").strip()
    reason = f"Purchase coding inherited from PO {po.po_number}"
    if sub:
        reason = f"{reason} / {sub}"
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger, config),
        rule_type="Purchase rule",
        match_reason=reason,
    )


def _fallback_mapping(config: RuleBookConfigPayload) -> ConfigMappingHit:
    ledger = config.posting_defaults.fallback_account
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger, config),
        rule_type=FALLBACK_RULE_TYPE,
        match_reason=f"No rule matched — {ledger}",
    )


def _rule_match_reason(rule_type: str, name: str) -> str:
    cleaned = (name or "").strip()
    prefix = f"{rule_type}:"
    if cleaned.lower().startswith(prefix.lower()):
        return cleaned
    return f"{rule_type}: {cleaned}"


def _hit_from_purchase_rule(
    doc,
    config: RuleBookConfigPayload,
) -> ConfigMappingHit | None:
    purchase = match_purchase_rule(doc, config.purchase_rules)
    if not purchase:
        return None
    ledger = purchase.post_to.ledger
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger, config),
        rule_type="Purchase rule",
        match_reason=_rule_match_reason("Purchase rule", purchase.name),
    )


def _hit_from_expense_rule(
    doc,
    config: RuleBookConfigPayload,
) -> ConfigMappingHit | None:
    expense = match_expense_rule(doc, config.expense_rules)
    if not expense:
        return None
    ledger = expense.post_to.ledger
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger, config),
        rule_type="Expense rule",
        match_reason=_rule_match_reason("Expense rule", expense.name),
    )


def _hit_from_team_rule(
    doc,
    config: RuleBookConfigPayload,
    *,
    amount: float | None,
) -> ConfigMappingHit | None:
    team = match_team_expense_rule(doc, config.team_expense_rules, amount=amount)
    if not team:
        return None
    ledger = team.post_to.ledger
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger, config),
        rule_type="Team expense rule",
        match_reason=_rule_match_reason("Team expense rule", team.name),
    )


def _resolve_legacy_and_fallback(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> ConfigMappingHit:
    legacy_hit = match_legacy_cascade(invoice, config.legacy_cascade)
    if legacy_hit:
        ledger, reason = legacy_hit
        return ConfigMappingHit(
            mapping=_ledger_to_mapping(ledger, config),
            rule_type=legacy_rule_type(),
            match_reason=reason,
        )
    return _fallback_mapping(config)


def resolve_config_mapping(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    purchase_order: PurchaseOrder | None = None,
) -> ConfigMappingHit:
    """Map using the routed category book, then legacy cascade → suspense fallback."""
    route = (invoice.route_target or "").strip()
    doc = invoice_to_eval_document(invoice)
    amount = _invoice_amount(invoice)

    if route == ROUTE_PURCHASE:
        if purchase_order is not None:
            inherited = mapping_hit_from_po(purchase_order, config)
            if inherited is not None:
                return inherited
        hit = _hit_from_purchase_rule(doc, config)
        if hit is not None:
            return hit
        return _resolve_legacy_and_fallback(invoice, config)

    if route == ROUTE_EXPENSES:
        if not is_staff_claim_sender(invoice.email_sender, config.employee_masters):
            hit = _hit_from_expense_rule(doc, config)
            if hit is not None:
                return hit
        return _resolve_legacy_and_fallback(invoice, config)

    if route == ROUTE_TEAM:
        hit = _hit_from_team_rule(doc, config, amount=amount)
        if hit is not None:
            return hit
        return _resolve_legacy_and_fallback(invoice, config)

    if route == ROUTE_VAULT:
        return _resolve_legacy_and_fallback(invoice, config)

    return _resolve_legacy_and_fallback(invoice, config)


def map_invoice_to_account(
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
) -> AccountMapping:
    """Map invoice header to GL account using the unified rule book."""
    return resolve_config_mapping(invoice, config).mapping


def map_invoice_with_details(
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
    line_description: str | None = None,
    purchase_order: PurchaseOrder | None = None,
) -> MappingDetail:
    """Map invoice with audit metadata using the unified rule book."""
    del line_description  # header-level rules; line text is in invoice line_items for eval
    hit = resolve_config_mapping(invoice, config, purchase_order=purchase_order)
    return MappingDetail(
        expense_category=hit.mapping.expense_category or hit.mapping.account_name,
        account_code=hit.mapping.account_code,
        account_name=hit.mapping.account_name,
        rule_type=hit.rule_type,
        match_reason=hit.match_reason,
    )


def is_fallback_mapping(detail: MappingDetail) -> bool:
    return detail.rule_type == FALLBACK_RULE_TYPE


def get_tax_account_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    return resolve_category_for_config(config.posting_defaults.tax_account, config)


def get_payable_account_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    return resolve_category_for_config(config.posting_defaults.payable_account, config)
