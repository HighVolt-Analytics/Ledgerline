"""Map invoices using the unified classification rule book."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.account_mapper import AccountMapping, MappingDetail, resolve_category
from app.services.rule_book_config_io import load_rule_book_config_dict
from app.services.rule_book_evaluate_service import invoice_to_eval_document
from app.services.legacy_cascade import legacy_rule_type, match_legacy_cascade
from app.services.rule_engine import (
    detect_vendor,
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


@lru_cache
def load_classification_config(org_id: int) -> RuleBookConfigPayload:
    raw = load_rule_book_config_dict(org_id)
    return validate_rule_book_config_payload(raw)


def clear_classification_config_cache() -> None:
    load_classification_config.cache_clear()


def _ledger_to_mapping(ledger: str) -> AccountMapping:
    resolved = resolve_category(ledger)
    return AccountMapping(
        account_code=resolved.account_code,
        account_name=resolved.account_name,
        expense_category=ledger,
    )


def _fallback_mapping(config: RuleBookConfigPayload) -> ConfigMappingHit:
    ledger = config.posting_defaults.fallback_account
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger),
        rule_type=FALLBACK_RULE_TYPE,
        match_reason=f"No rule matched — {ledger}",
    )


def resolve_config_mapping(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> ConfigMappingHit:
    """Apply purchase → team → expense → vendor master → fallback from classification config."""
    doc = invoice_to_eval_document(invoice)
    amount = _invoice_amount(invoice)

    purchase = match_purchase_rule(doc, config.purchase_rules)
    if purchase:
        ledger = purchase.post_to.ledger
        return ConfigMappingHit(
            mapping=_ledger_to_mapping(ledger),
            rule_type="Purchase rule",
            match_reason=f"Purchase rule: {purchase.name}",
        )

    team = match_team_expense_rule(doc, config.team_expense_rules, amount=amount)
    if team:
        ledger = team.post_to.ledger
        return ConfigMappingHit(
            mapping=_ledger_to_mapping(ledger),
            rule_type="Team expense rule",
            match_reason=f"Team expense rule: {team.name}",
        )

    expense = match_expense_rule(doc, config.expense_rules)
    if expense:
        ledger = expense.post_to.ledger
        return ConfigMappingHit(
            mapping=_ledger_to_mapping(ledger),
            rule_type="Expense rule",
            match_reason=f"Expense rule: {expense.name}",
        )

    vendor_match = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
    if (
        vendor_match.vendor
        and vendor_match.confidence >= config.vendor_detection_config.threshold
    ):
        ledger = (vendor_match.vendor.default_ledger or "").strip()
        if ledger and ledger != "—":
            return ConfigMappingHit(
                mapping=_ledger_to_mapping(ledger),
                rule_type="Vendor master",
                match_reason=f"Vendor master: {vendor_match.vendor.name}",
            )

    legacy_hit = match_legacy_cascade(invoice, config.legacy_cascade)
    if legacy_hit:
        ledger, reason = legacy_hit
        return ConfigMappingHit(
            mapping=_ledger_to_mapping(ledger),
            rule_type=legacy_rule_type(),
            match_reason=reason,
        )

    return _fallback_mapping(config)


def map_invoice_to_account(invoice: Invoice) -> AccountMapping:
    """Map invoice header to GL account using the unified rule book."""
    config = load_classification_config(invoice.org_id)
    return resolve_config_mapping(invoice, config).mapping


def map_invoice_with_details(
    invoice: Invoice,
    *,
    line_description: str | None = None,
) -> MappingDetail:
    """Map invoice with audit metadata using the unified rule book."""
    del line_description  # header-level rules; line text is in invoice line_items for eval
    config = load_classification_config(invoice.org_id)
    hit = resolve_config_mapping(invoice, config)
    return MappingDetail(
        expense_category=hit.mapping.expense_category or hit.mapping.account_name,
        account_code=hit.mapping.account_code,
        account_name=hit.mapping.account_name,
        rule_type=hit.rule_type,
        match_reason=hit.match_reason,
    )


def is_fallback_mapping(detail: MappingDetail) -> bool:
    return detail.rule_type == FALLBACK_RULE_TYPE


def get_tax_account_mapping(org_id: int) -> AccountMapping:
    config = load_classification_config(org_id)
    return resolve_category(config.posting_defaults.tax_account)


def get_payable_account_mapping(org_id: int) -> AccountMapping:
    config = load_classification_config(org_id)
    return resolve_category(config.posting_defaults.payable_account)
