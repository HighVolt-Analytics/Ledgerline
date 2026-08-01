"""Map invoices using document-type Post to GL (tenant chart of accounts)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload
from app.services.rule_book.account_mapper import AccountMapping, MappingDetail, resolve_category_for_config
from app.services.classification.document_type_post_to_service import (
    DocumentTypePostToMissingError,
    document_type_requires_post_to,
    ensure_transactional_post_to_or_raise,
    resolve_document_type_definition_for_invoice,
)
from app.services.rule_book.rule_book_config_io import load_rule_book_config_with_masters

ROUTE_PURCHASE = "Purchase Management"
ROUTE_SALES = "Sales Management"
ROUTE_EXPENSES = "Expenses Management"
ROUTE_TEAM = "Team Expenses"
ROUTE_VAULT = "Vault"

FALLBACK_RULE_TYPE = "Fallback"
DOCUMENT_TYPE_RULE_TYPE = "Document type"


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
    from app.services.classification.document_type_catalog import clear_document_type_catalog_cache
    from app.services.rule_book.rule_book_config_io import clear_posting_config_cache

    clear_document_type_catalog_cache()
    clear_posting_config_cache()


def _ledger_to_mapping(ledger: str, config: RuleBookConfigPayload) -> AccountMapping:
    resolved = resolve_category_for_config(ledger, config)
    return AccountMapping(
        account_code=resolved.account_code,
        account_name=resolved.account_name,
        expense_category=ledger,
    )


def _fallback_mapping(config: RuleBookConfigPayload) -> ConfigMappingHit:
    ledger = config.posting_defaults.fallback_account
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger, config),
        rule_type=FALLBACK_RULE_TYPE,
        match_reason=f"No Post to configured — {ledger}",
    )


def _hit_from_document_type(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> ConfigMappingHit | None:
    definition = ensure_transactional_post_to_or_raise(invoice, config)
    if definition is None:
        return None
    post = definition.post_to
    ledger = (post.ledger or "").strip()
    if not ledger:
        return None
    code = definition.code.strip().upper()
    return ConfigMappingHit(
        mapping=_ledger_to_mapping(ledger, config),
        rule_type=DOCUMENT_TYPE_RULE_TYPE,
        match_reason=f"Document type {code}: {definition.title}",
    )


def resolve_sales_post_accounts(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    sales_order: SalesOrder | None = None,
) -> tuple[str, str]:
    """Return (receivable_account_label, tax_account_label) for sales journals.

    Receivable control comes from Rule Book posting defaults (single AR parent).
    Tax may still come from the document-type Post to override.
    """
    del sales_order
    recv = (config.posting_defaults.receivable_account or "").strip() or "Accounts Receivable"
    tax = "Tax Collected"
    definition = resolve_document_type_definition_for_invoice(invoice, config)
    if definition is not None:
        post = definition.post_to
        tax_override = (post.tax_account or "").strip()
        if tax_override:
            tax = tax_override
    return (recv, tax)


def resolve_config_mapping(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    purchase_order: PurchaseOrder | None = None,
    sales_order: SalesOrder | None = None,
) -> ConfigMappingHit:
    """Map using document-type Post to, then fallback for non-transactional types."""
    del purchase_order, sales_order
    definition = resolve_document_type_definition_for_invoice(invoice, config)
    if document_type_requires_post_to(definition):
        hit = _hit_from_document_type(invoice, config)
        if hit is not None:
            return hit
        raise DocumentTypePostToMissingError(
            f"Document type {(invoice.document_type_code or '?').strip().upper()} "
            "has no Post to ledger — configure it in Rule Book → Document types."
        )

    post = definition.post_to if definition is not None else None
    ledger = (post.ledger or "").strip() if post is not None else ""
    if ledger:
        return ConfigMappingHit(
            mapping=_ledger_to_mapping(ledger, config),
            rule_type=DOCUMENT_TYPE_RULE_TYPE,
            match_reason=f"Document type optional Post to: {ledger}",
        )
    return _fallback_mapping(config)


def map_invoice_to_account(
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
) -> AccountMapping:
    """Map invoice header to GL account using document-type Post to."""
    return resolve_config_mapping(invoice, config).mapping


def map_invoice_with_details(
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
    line_description: str | None = None,
    purchase_order: PurchaseOrder | None = None,
    sales_order: SalesOrder | None = None,
) -> MappingDetail:
    """Map invoice with audit metadata using document-type Post to."""
    del line_description, purchase_order, sales_order
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


def get_tax_account_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    return resolve_category_for_config(config.posting_defaults.tax_account, config)


def get_payable_account_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    return resolve_category_for_config(config.posting_defaults.payable_account, config)


def get_receivable_account_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    label = (config.posting_defaults.receivable_account or "").strip() or "Accounts Receivable"
    return resolve_category_for_config(label, config)


def get_bank_account_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    return resolve_category_for_config(config.posting_defaults.bank_account, config)


def team_settlement_account_label(config: RuleBookConfigPayload) -> str:
    """
    Settlement ledger label for Team Expenses payouts and reimbursements.

    Tenants provisioned before Team Expenses posting existed keep the shared bank account,
    so an unconfigured or unknown settlement label resolves to it rather than blocking.
    """
    from app.services.rule_book.account_mapper import category_resolved_in_coa

    bank = (config.posting_defaults.bank_account or "").strip()
    label = (config.team_expense_posting.settlement_account or "").strip()
    if not label:
        return bank
    if category_resolved_in_coa(label, config):
        return label
    return bank or label


def get_team_settlement_account_mapping(config: RuleBookConfigPayload) -> AccountMapping:
    return resolve_category_for_config(team_settlement_account_label(config), config)
